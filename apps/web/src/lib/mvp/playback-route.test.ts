import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { randomUUID } from "node:crypto";
import sharp from "sharp";
import * as storage from "./store";
import { GET, HEAD, POST } from "../../app/api/mvp/[[...path]]/route";
let db:storage.JobStore;
const token="w".repeat(32);
beforeEach(()=>{
 vi.stubEnv("MVP_LOCAL_ENABLED","1");vi.stubEnv("VERCEL","");vi.stubEnv("MVP_WORKER_TOKEN",token);
 db=new storage.JobStore(":memory:");vi.spyOn(storage,"getStore").mockReturnValue(db);
});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllEnvs();db.db.close();});
const context=(path:string[])=>({params:Promise.resolve({path})});
test("状态 API 返回全局未完成数量和 500 条上限",async()=>{
 db.create({requestId:randomUUID(),mode:"h3_t2v",prompt:"queue",width:640,height:360,seed:1,denoise:1},null);
 const state=await (await GET(request("state"),context(["state"]))).json();
 expect(state.queue).toEqual({active:1,limit:500});
 expect(state.workflows.filter((o:{engine:string})=>o.engine==="director")).toHaveLength(3);
 expect(state.workflows.filter((o:{engine:string;ready:boolean})=>o.engine==="director").every((o:{ready:boolean})=>!o.ready)).toBe(true);
});
test("API 拒绝未就绪引擎和浏览器版本，原生元信息随领取传递且媒体上传仍兼容",async()=>{
 const params={requestId:randomUUID(),mode:"h3_t2v",prompt:"test",width:640,height:360,seed:1,denoise:1};
 for(const [extra,status] of [[{workflowEngine:"director"},503],[{workflowEngine:"unknown"},400],[{workflowRevision:"fake"},400]] as const) {
   const form=new FormData();form.set("params",JSON.stringify({...params,...extra}));
   expect((await POST(request("jobs","POST",form,{origin:"http://127.0.0.1:3000"}),context(["jobs"]))).status).toBe(status);
 }
 expect(db.state().jobs).toHaveLength(0);
 const form=new FormData();form.set("params",JSON.stringify(params));
 const accepted=await POST(request("jobs","POST",form,{origin:"http://127.0.0.1:3000"}),context(["jobs"]));
 expect(accepted.status).toBe(201);const job=await accepted.json();
 const claim=await POST(request("worker/claim","POST",JSON.stringify({worker_id:randomUUID(),available_modes:["h3_t2v"]}),{authorization:`Bearer ${token}`}),context(["worker","claim"]));
 const claimed=(await claim.json()).job;
 expect(claimed).toMatchObject({workflowEngine:"native",workflowRevision:job.workflowRevision,workflowOutputNodeIds:job.workflowOutputNodeIds});
 db.update(job.id,claimed.lease,"running","accepted","prompt");db.update(job.id,claimed.lease,"uploading","saving");
 const done=await POST(request("worker/complete","POST",new Uint8Array(mp4()),{authorization:`Bearer ${token}`,"x-job-id":job.id,"x-lease-id":claimed.lease}),context(["worker","complete"]));
 expect(done.status).toBe(200);expect((await done.json()).workflowRevision).toBe(job.workflowRevision);
});
test("关闭图片生成后拒绝新增图片，保留历史查询和原提交编号",async()=>{
 vi.stubEnv("MVP_IMAGE_GENERATION_ENABLED","0");
 const old={requestId:randomUUID(),mode:"text" as const,prompt:"old image",width:256,height:256,seed:1,denoise:1};
 const history=db.create(old,null);
 const replay=new FormData();replay.set("params",JSON.stringify(old));
 const headers={origin:"http://127.0.0.1:3000"};
 expect((await POST(request("jobs","POST",replay,headers),context(["jobs"]))).status).toBe(201);
 const fresh=new FormData();fresh.set("params",JSON.stringify({...old,requestId:randomUUID()}));
 expect((await POST(request("jobs","POST",fresh,headers),context(["jobs"]))).status).toBe(410);
 const state=await (await GET(request("state"),context(["state"]))).json();
 expect(state.features.imageGeneration).toBe(false);expect(state.jobs[0].id).toBe(history.id);
 const claim=await POST(request("worker/claim","POST",JSON.stringify({worker_id:randomUUID()}),{authorization:`Bearer ${token}`}),context(["worker","claim"]));
 expect((await claim.json()).job).toBeNull();expect(db.state().jobs).toHaveLength(1);
});
function request(path:string,method="GET",body?:BodyInit,extra:Record<string,string>={}) {return new Request(`http://127.0.0.1:3000/api/mvp/${path}`,{method,body,headers:{host:"127.0.0.1:3000",...extra}});}
function uploading() {
 const job=db.create({requestId:randomUUID(),mode:"h3_t2v",prompt:"test",width:640,height:360,seed:1,denoise:1},null);
 const claimed=db.claim(randomUUID())!;db.update(job.id,claimed.lease,"running","accepted","prompt");db.update(job.id,claimed.lease,"uploading","saving");return {...job,lease:claimed.lease};
}
// Structural container fixture: real media decoding is covered by the Python tests.
function mp4() {return Buffer.concat([["ftyp",8],["moov",0],["mdat",8]].map(([name,size])=>{const b=Buffer.alloc(Number(size)+8);b.writeUInt32BE(b.length);b.write(String(name),4);return b;}));}
test("视频与封面完成上传后，HEAD、封面、Range 和缓存均可用",async()=>{
 const job=uploading(),raw=mp4();const poster=new Uint8Array(await sharp({create:{width:64,height:36,channels:3,background:"blue"}}).jpeg().toBuffer());
 const form=new FormData();form.set("video",new File([new Uint8Array(raw)],"clip.mp4"));form.set("poster",new File([poster],"poster.jpg"));
 const done=await POST(request("worker/complete","POST",form,{authorization:`Bearer ${token}`,"x-job-id":job.id,"x-lease-id":job.lease}),context(["worker","complete"]));
 expect(done.status).toBe(200);expect((await done.json()).has_poster).toBe(true);
 const path=["jobs",job.id,"media"];
 const head=await HEAD(request(path.join("/"),"HEAD"),context(path));expect(head.status).toBe(200);expect(await head.text()).toBe("");expect(head.headers.get("content-length")).toBe(String(raw.length));
 const cached=await GET(request(path.join("/"),"GET",undefined,{"if-none-match":head.headers.get("etag")!}),context(path));expect(cached.status).toBe(304);
 const partial=await GET(request(path.join("/"),"GET",undefined,{range:"bytes=2-7"}),context(path));expect(partial.status).toBe(206);expect(Buffer.from(await partial.arrayBuffer())).toEqual(raw.subarray(2,8));
 const image=await GET(request(`jobs/${job.id}/poster`),context(["jobs",job.id,"poster"]));expect(image.headers.get("content-type")).toBe("image/jpeg");expect((await sharp(Buffer.from(await image.arrayBuffer())).metadata()).width).toBe(64);
 expect(db.state().jobs[0].has_poster).toBe(true);expect(JSON.stringify(db.state())).not.toContain('"poster":');
});
test("伪装封面不写入结果；未配置主机的 HEAD 仍被拒绝",async()=>{
 const job=uploading(),form=new FormData();form.set("video",new File([new Uint8Array(mp4())],"clip.mp4"));form.set("poster",new File(["invalid"],"poster.jpg"));
 const result=await POST(request("worker/complete","POST",form,{authorization:`Bearer ${token}`,"x-job-id":job.id,"x-lease-id":job.lease}),context(["worker","complete"]));
 expect(result.status).toBe(400);expect(db.row(job.id).status).toBe("uploading");
 const denied=await HEAD(request(`jobs/${job.id}/media`,"HEAD",undefined,{host:"untrusted.example"}),context(["jobs",job.id,"media"]));expect(denied.status).toBe(403);
});

test("多兆参考图片进入队列后可按提交编号确认，重传不会重复创建",async()=>{
 const params={requestId:randomUUID(),mode:"h3_r2v",prompt:"照片中的人物在草原上跑，后面有一只豹子在追她",width:640,height:360,seed:1,denoise:1,frames:124,durationSeconds:5,fps:24};
 const png=await sharp({create:{width:1672,height:941,channels:3,background:"blue"}}).png().toBuffer();
 const bytes=new Uint8Array(Buffer.concat([png,Buffer.alloc(2*1024*1024)]));
 const form=new FormData();form.set("params",JSON.stringify(params));form.set("ref_image_0",new File([bytes],"test.png",{type:"image/png"}));
 const headers={origin:"http://127.0.0.1:3000","x-request-id":params.requestId};
 const result=await POST(request("jobs","POST",form,headers),context(["jobs"]));expect(result.status).toBe(201);const job=await result.json();
 const path=["jobs","request",params.requestId];
 const found=await GET(request(path.join("/")),context(path));expect(found.status).toBe(200);expect((await found.json()).id).toBe(job.id);
 const repeated=await POST(request("jobs","POST",form,headers),context(["jobs"]));expect((await repeated.json()).id).toBe(job.id);expect(db.state().jobs).toHaveLength(1);
 const missing=await GET(request("jobs/request/"+randomUUID()),context(["jobs","request",randomUUID()]));expect(missing.status).toBe(404);
 const denied=await GET(request(path.join("/"),"GET",undefined,{host:"untrusted.example"}),context(path));expect(denied.status).toBe(403);
});
