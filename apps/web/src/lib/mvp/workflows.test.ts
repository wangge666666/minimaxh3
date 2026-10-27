import { afterEach, expect, test, vi } from "vitest";
import { mkdtempSync, readFileSync, writeFileSync, rmSync, cpSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve, join } from "node:path";
import { randomUUID } from "node:crypto";
import { createSchema } from "./schema";
import { pinWorkflow, workflowOptions } from "./workflows";
import { JobStore } from "./store";

const directories: string[] = [];
afterEach(() => { vi.unstubAllEnvs(); directories.splice(0).forEach(path => rmSync(path, { recursive: true, force: true })); });
function fixture() {
  const path = mkdtempSync(join(tmpdir(), "hub-workflow-")); directories.push(path);
  cpSync(resolve("../../workflows"), path, { recursive: true });
  return path;
}
const params = () => ({ requestId: randomUUID(), mode: "h3_t2v" as const, prompt: "test", width: 640, height: 360, seed: 1, denoise: 1 });

test("旧请求默认为原生；客户端不得指定版本、输出、节点或未知引擎", () => {
  expect(pinWorkflow(createSchema.parse(params()))).toMatchObject({workflowEngine:"native",steps:20,frames:124,fps:24,sound:true,referenceVideoAudio:true,refImageSize:"match"});
  for (const extra of [{workflowEngine:"turbo"}, {workflowEngine:null}, {workflowRevision:"fake"}, {workflowOutputNodeIds:["1"]}, {graph:{}}, {workflowDirectory:"/tmp"}]) {
    expect(createSchema.safeParse({...params(), ...extra}).success).toBe(false);
  }
});
test("三个导演台入口在缺表、未对接表和伪造可用表时都保持未就绪", () => {
  const path = fixture();
  for (const registry of [null, "invalid", JSON.stringify({ready:true,modes:["h3_t2v","h3_i2v","h3_r2v"]})]) {
    if (registry !== null) writeFileSync(join(path,"h3_capabilities.json"),registry);
    const options = workflowOptions(path);
    expect(options.filter(o=>o.engine==="native").every(o=>o.ready && o.defaults.steps===20)).toBe(true);
    expect(options.filter(o=>o.engine==="director")).toHaveLength(3);
    expect(options.filter(o=>o.engine==="director").every(o=>!o.ready)).toBe(true);
    expect(()=>pinWorkflow({...params(),workflowEngine:"director"},path)).toThrow("未就绪");
  }
});
test("入队固定版本和输出，配置改变不会改变排队记录；重试仍返回原任务", () => {
  const path = fixture(); vi.stubEnv("MVP_WORKFLOW_DIRECTORY",path);
  const db = new JobStore(":memory:");
  try {
    const p=params(), first=db.create(p,null);
    expect(first.workflowRevision).toMatch(/^native-sha256:[a-f0-9]{64}$/);
    const file=join(path,"h3_t2v_api.json");writeFileSync(file,readFileSync(file,"utf8")+"\n");
    expect(db.state().jobs[0].workflowRevision).toBe(first.workflowRevision);
    expect(db.claim(randomUUID())?.workflowOutputNodeIds).toEqual(first.workflowOutputNodeIds);
    rmSync(file);
    expect(db.create(p,null).id).toBe(first.id);
    expect(()=>db.create(params(),null)).toThrow("原生工作流");
  } finally { db.db.close(); }
});
test("Windows CRLF 与 Unix LF 得到相同版本；缺失安装不会显示原生可用", () => {
  const path=fixture(), before=pinWorkflow(params(),path);
  for(const suffix of ["api","mapping"]) {
    const file=join(path,`h3_t2v_${suffix}.json`);writeFileSync(file,readFileSync(file,"utf8").replace(/\n/g,"\r\n"));
  }
  expect(pinWorkflow(params(),path).workflowRevision).toBe(before.workflowRevision);
  rmSync(join(path,"h3_t2v_api.json"));
  expect(workflowOptions(path).find(o=>o.mode==="h3_t2v" && o.engine==="native")?.ready).toBe(false);
});
test("旧库一致副本重复打开后保留 prompt、租约、素材、结果、封面及原始参数", () => {
  const directory=fixture(), original=new JobStore(join(directory,"old.sqlite"));
  const p={...params(),mode:"h3_r2v" as const}, bytes=new Uint8Array([1,2,3]);
  const job=original.create(p,null,[{key:"ref_audio_0",kind:"audio",name:"voice.wav",mime:"audio/wav",data:bytes}]);
  const claimed=original.claim(randomUUID())!;
  original.update(job.id,claimed.lease,"running","accepted","old-prompt");
  original.update(job.id,claimed.lease,"uploading","saving");original.complete(job.id,claimed.lease,bytes,bytes);
  original.db.prepare("UPDATE jobs SET params=? WHERE id=?").run(JSON.stringify(p),job.id);
  const copy=join(directory,"copy.sqlite");original.db.prepare("VACUUM INTO ?").run(copy);original.db.close();
  for(let i=0;i<2;i++) {
    const reopened=new JobStore(copy);
    try {
      const row=reopened.row(job.id);
      expect(row.params).toBe(JSON.stringify(p));expect(row.prompt_id).toBe("old-prompt");expect(row.lease).toBe(claimed.lease);
      expect(row.output).toEqual(bytes);expect(row.poster).toEqual(bytes);
      expect(reopened.state().jobs[0]).toMatchObject({workflowEngine:"native",has_poster:true,assets:[{key:"ref_audio_0"}]});
      expect(reopened.db.prepare("SELECT data FROM job_assets WHERE job_id=?").get(job.id)).toEqual({data:bytes});
      expect(reopened.db.prepare("PRAGMA integrity_check").get()).toEqual({integrity_check:"ok"});
    } finally {reopened.db.close();}
  }
});
