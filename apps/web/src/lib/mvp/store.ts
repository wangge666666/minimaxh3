import { DatabaseSync } from "node:sqlite";
import { mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { randomUUID } from "node:crypto";
import { isVideoMode, type CreateJob, type Job } from "./schema";
import { checkAssetRoles, type Asset } from "./h3";
import { maxActiveJobs, recentHistoryLimit } from "./queue";
import { pinWorkflow } from "./workflows";
export type StoredAsset = Asset & { data: Uint8Array };

export class StoreError extends Error { constructor(message: string, public status = 409) { super(message); } }
type Row = { id: string; params: string; status: string; created_at: number; updated_at: number; message: string; prompt_id: string | null; lease: string | null; worker_id: string | null; lease_until: number | null; input: Uint8Array | null; output: Uint8Array | null; poster:Uint8Array|null };
export class JobStore {
  db: DatabaseSync;
  constructor(path: string) {
    this.db = new DatabaseSync(path);
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;
      CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, params TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('queued','claimed','running','uploading','completed','failed','canceled')),
        created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, message TEXT NOT NULL DEFAULT '',
        prompt_id TEXT, worker_id TEXT, lease TEXT, lease_until INTEGER, input BLOB, output BLOB);
      CREATE INDEX IF NOT EXISTS jobs_status_created ON jobs(status,created_at);
      CREATE TABLE IF NOT EXISTS job_assets (job_id TEXT NOT NULL, key TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, mime TEXT NOT NULL, data BLOB NOT NULL, PRIMARY KEY(job_id,key));
      CREATE TABLE IF NOT EXISTS worker (id TEXT PRIMARY KEY, seen INTEGER NOT NULL, name TEXT NOT NULL);`);
    const columns=this.db.prepare("PRAGMA table_info(worker)").all() as {name:string}[];
    for(const name of ["h3_online","local_online"]) if(!columns.some(c=>c.name===name)) this.db.exec(`ALTER TABLE worker ADD COLUMN ${name} INTEGER NOT NULL DEFAULT 0`);
    if(!(this.db.prepare("PRAGMA table_info(jobs)").all() as {name:string}[]).some(c=>c.name==="poster")) this.db.exec("ALTER TABLE jobs ADD COLUMN poster BLOB");
  }
  transaction<T>(fn: () => T): T {
    this.db.exec("BEGIN IMMEDIATE");
    try { const value = fn(); this.db.exec("COMMIT"); return value; }
    catch (e) { this.db.exec("ROLLBACK"); throw e; }
  }
  expire() {
    this.db.prepare("UPDATE jobs SET status='failed', message='Worker 租约超时，执行结果不确定。请核对 ComfyUI 历史后再创建任务，系统不会自动重复提交。', updated_at=? WHERE status IN ('claimed','running','uploading') AND lease_until < ?").run(Date.now(), Date.now());
  }
  row(id: string): Row {
    const row = this.db.prepare("SELECT * FROM jobs WHERE id=?").get(id) as Row | undefined;
    if (!row) throw new StoreError("任务不存在", 404);
    return row;
  }
  resultInfo(id:string,kind:"output"|"poster") {
    const column=kind==="poster"?"poster":"output";
    const row=this.db.prepare(`SELECT params,status,length(${column}) AS size FROM jobs WHERE id=?`).get(id) as {params:string;status:string;size:number|null}|undefined;
    if(!row || row.status!=="completed" || !row.size) throw new StoreError("结果尚未生成",404);
    return row;
  }
  resultBytes(id:string,kind:"output"|"poster",start:number,end:number): Uint8Array {
    const column=kind==="poster"?"poster":"output";
    const row=this.db.prepare(`SELECT substr(${column},?,?) AS bytes FROM jobs WHERE id=? AND status='completed'`).get(start+1,end-start+1,id) as {bytes:Uint8Array}|undefined;
    if(!row?.bytes) throw new StoreError("结果尚未生成",404);
    return row.bytes;
  }
  publicJob(row: Row): Job {
    const position = row.status === "queued" ? Number((this.db.prepare("SELECT count(*) AS n FROM jobs WHERE status='queued' AND (created_at < ? OR (created_at=? AND rowid <= (SELECT rowid FROM jobs WHERE id=?)))").get(row.created_at,row.created_at,row.id) as { n: number }).n) : null;
    const params=JSON.parse(row.params);
    return { ...params, workflowEngine:params.workflowEngine===undefined?"native":params.workflowEngine, assets:this.assets(row), has_poster:!!row.poster, media_type:isVideoMode(params.mode)?"video":"image", id: row.id, status: row.status, created_at: row.created_at, updated_at: row.updated_at, message: row.message, prompt_id: row.prompt_id, queue_position: position };
  }
  findByRequestId(requestId:string):Job|null {
    const row=this.db.prepare("SELECT id,params,status,created_at,updated_at,message,prompt_id,lease,worker_id,lease_until,CASE WHEN input IS NOT NULL THEN x'01' ELSE NULL END AS input,NULL AS output,CASE WHEN poster IS NOT NULL THEN x'01' ELSE NULL END AS poster FROM jobs WHERE request_id=?").get(requestId) as Row|undefined;
    return row?this.publicJob(row):null;
  }
  assets(row: Row): Asset[] {
    const assets = this.db.prepare("SELECT key,kind,name,mime FROM job_assets WHERE job_id=? ORDER BY key").all(row.id) as Asset[];
    const mode=JSON.parse(row.params).mode;
    if (!assets.length && row.input) assets.push({key:mode==="h3_i2v"?"first_frame":mode==="h3_r2v"?"ref_image_0":"reference",kind:"image",name:"reference.png",mime:"image/png"});
    return assets;
  }
  asset(id: string, lease: string, key: string): StoredAsset {
    const row = this.owned(id,lease);
    if (!["claimed","running"].includes(row.status)) throw new StoreError("参考素材不可用",404);
    const asset = this.db.prepare("SELECT key,kind,name,mime,data FROM job_assets WHERE job_id=? AND key=?").get(id,key) as StoredAsset | undefined;
    if (asset) return asset;
    const legacy = this.assets(row).find(a=>a.key===key);
    if (legacy && row.input) return {...legacy,data:row.input};
    throw new StoreError("参考素材不存在",404);
  }
  create(params: CreateJob, image: Uint8Array | null, assets: StoredAsset[] = []) {
    return this.transaction(() => {
      this.expire();
      const existing = this.db.prepare("SELECT * FROM jobs WHERE request_id=?").get(params.requestId) as Row | undefined;
      if (existing) return this.publicJob(existing);
      const pinned = pinWorkflow(params);
      const active = this.db.prepare("SELECT count(*) AS n FROM jobs WHERE status IN ('queued','claimed','running','uploading')").get() as {n:number};
      if (active.n >= maxActiveJobs) throw new StoreError(`最多保留 ${maxActiveJobs} 个未完成任务，请等待完成后再提交`, 429);
      const legacy = image ? [{key:params.mode==="h3_i2v"?"first_frame":params.mode==="h3_r2v"?"ref_image_0":"reference",kind:"image" as const}] : [];
      try { checkAssetRoles(params.mode, [...assets,...legacy]); } catch (e) { throw new StoreError((e as Error).message,400); }
      const id = randomUUID(), now = Date.now();
      this.db.prepare("INSERT INTO jobs(id,request_id,params,status,created_at,updated_at,input) VALUES(?,?,?,'queued',?,?,?)").run(id,params.requestId,JSON.stringify(pinned),now,now,image);
      const insert=this.db.prepare("INSERT INTO job_assets(job_id,key,kind,name,mime,data) VALUES(?,?,?,?,?,?)");
      for (const asset of assets) insert.run(id,asset.key,asset.kind,asset.name,asset.mime,asset.data);
      return this.publicJob(this.row(id));
    });
  }
  state() {
    this.expire();
    // Polling must never materialize the videos stored in each row.
    // Keep every active job visible, including the oldest job the Worker may resume.
    const rows = this.db.prepare("SELECT id,params,status,created_at,updated_at,message,prompt_id,lease,worker_id,lease_until,CASE WHEN input IS NOT NULL THEN x'01' ELSE NULL END AS input,NULL AS output,CASE WHEN poster IS NOT NULL THEN x'01' ELSE NULL END AS poster FROM jobs WHERE status IN ('queued','claimed','running','uploading') OR id IN (SELECT id FROM jobs WHERE status IN ('completed','failed','canceled') ORDER BY created_at DESC,rowid DESC LIMIT ?) ORDER BY created_at DESC,rowid DESC").all(recentHistoryLimit) as Row[];
    const active = this.db.prepare("SELECT count(*) AS n FROM jobs WHERE status IN ('queued','claimed','running','uploading')").get() as {n:number};
    const worker = this.db.prepare("SELECT id,name,seen,h3_online,local_online FROM worker ORDER BY seen DESC LIMIT 1").get() as {id:string;name:string;seen:number;h3_online:number;local_online:number}|undefined;
    return { jobs: rows.map(r => this.publicJob(r)), queue: {active:active.n,limit:maxActiveJobs}, worker: worker ? { ...worker, online: Date.now()-worker.seen < 15000, h3_online:!!worker.h3_online && Date.now()-worker.seen < 15000, local_online:!!worker.local_online && Date.now()-worker.seen < 15000 } : null, mode: "local-mvp" };
  }
  heartbeat(workerId: string, health?: {h3_online?:boolean;local_online?:boolean}) {
    this.db.prepare("INSERT INTO worker(id,seen,name,h3_online,local_online) VALUES(?,?,'私网生成 Worker',?,?) ON CONFLICT(id) DO UPDATE SET seen=excluded.seen,h3_online=coalesce(?,worker.h3_online),local_online=coalesce(?,worker.local_online)").run(workerId,Date.now(),health?.h3_online?1:0,health?.local_online?1:0,health?.h3_online===undefined?null:Number(health.h3_online),health?.local_online===undefined?null:Number(health.local_online));
  }
  claim(workerId: string, availableModes?:string[]) {
    return this.transaction(() => {
      this.expire(); this.heartbeat(workerId);
      if (this.db.prepare("SELECT id FROM jobs WHERE status IN ('claimed','running','uploading') LIMIT 1").get()) return null;
      if(availableModes?.length===0) return null;
      const filter=availableModes ? ` AND json_extract(params,'$.mode') IN (${availableModes.map(()=>"?").join(",")})` : "";
      const row = this.db.prepare(`SELECT * FROM jobs WHERE status='queued'${filter} ORDER BY created_at,rowid LIMIT 1`).get(...(availableModes??[])) as Row|undefined;
      if (!row) return null;
      const lease = randomUUID(), now = Date.now();
      this.db.prepare("UPDATE jobs SET status='claimed',worker_id=?,lease=?,lease_until=?,updated_at=?,message='Worker 已领取' WHERE id=? AND status='queued'").run(workerId,lease,now+90000,now,row.id);
      return { ...this.publicJob(this.row(row.id)), lease, has_input: !!row.input };
    });
  }
  owned(id: string, lease: string): Row {
    this.expire(); const row=this.row(id);
    if (row.lease !== lease) throw new StoreError("任务租约不匹配",403);
    return row;
  }
  update(id: string, lease: string, status: string, message: string, promptId?: string) {
    return this.transaction(() => {
      const row=this.owned(id,lease);
      if (["completed","failed","canceled"].includes(row.status)) {
        if (status===row.status) return this.publicJob(row);
        throw new StoreError("任务已终止，请核对执行状态");
      }
      const allowed: Record<string,string[]> = { claimed:["claimed","running","failed"],running:["running","uploading","failed"],uploading:["uploading","failed"] };
      if (!allowed[row.status]?.includes(status)) throw new StoreError("无效状态转换");
      if (row.prompt_id && promptId && row.prompt_id!==promptId) throw new StoreError("ComfyUI 任务 ID 不可替换");
      this.db.prepare("UPDATE jobs SET status=?,message=?,prompt_id=coalesce(?,prompt_id),lease_until=?,updated_at=? WHERE id=?").run(status,message,promptId??null,Date.now()+90000,Date.now(),id);
      if (row.worker_id) this.heartbeat(row.worker_id);
      return this.publicJob(this.row(id));
    });
  }
  complete(id: string, lease: string, image: Uint8Array, poster:Uint8Array|null=null) {
    return this.transaction(() => {
      const row = this.owned(id,lease);
      if (row.status === "completed") return this.publicJob(row);
      if (row.status !== "uploading" || !row.prompt_id) throw new StoreError("仅已提交 ComfyUI 且正在上传的任务可以完成");
      this.db.prepare("UPDATE jobs SET status='completed',output=?,poster=?,message='生成完成',updated_at=? WHERE id=?").run(image,poster,Date.now(),id);
      return this.publicJob(this.row(id));
    });
  }
  cancel(id: string) {
    const result=this.db.prepare("UPDATE jobs SET status='canceled',message='用户取消',updated_at=? WHERE id=? AND status='queued'").run(Date.now(),id);
    if (!result.changes) throw new StoreError("只能取消尚未领取的任务");
    return this.publicJob(this.row(id));
  }
}
let store: JobStore | undefined;
export function getStore() {
  if (!store) { const path=resolve(/* turbopackIgnore: true */ process.env.MVP_DATABASE_PATH || join(process.cwd(),".local-data","mvp.sqlite")); mkdirSync(dirname(path),{recursive:true,mode:0o700}); store=new JobStore(path); }
  return store;
}
