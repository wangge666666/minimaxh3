import { afterEach, beforeEach, expect, test } from "vitest";
import { randomUUID } from "node:crypto";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { JobStore } from "./store";
import type { CreateJob } from "./schema";
let store:JobStore;
beforeEach(()=>{store=new JobStore(":memory:");});
afterEach(()=>store.db.close());
const params=(overrides:Partial<CreateJob>={}):CreateJob=>({requestId:randomUUID(),mode:"text",prompt:"a small house",width:512,height:512,seed:1,denoise:0.6,...overrides});
test("500 个未完成任务包含生成中任务，满额重试仍幂等，取消后释放名额",()=>{
 const p=params();const first=store.create(p,null);expect(store.create(p,null).id).toBe(first.id);
 let last=first;
 for(let i=0;i<499;i++)last=store.create(params(),null);
 const claimed=store.claim(randomUUID())!;
 store.update(first.id,claimed.lease,"running","generating","prompt-running");
 expect(()=>store.create(params(),null)).toThrow("最多保留 500 个未完成任务");
 expect(store.create(p,null).id).toBe(first.id);
 expect(store.state().queue).toEqual({active:500,limit:500});
 expect(store.state().jobs).toHaveLength(500);
 store.cancel(last.id);
 expect(store.create(params(),null).status).toBe("queued");
 expect(store.state().queue.active).toBe(500);
 expect(store.claim(randomUUID())).toBeNull();
});

test("超过 50 条新历史不会隐藏较早的生成中任务和排队任务",()=>{
 const running=store.create(params(),null);
 const claimed=store.claim(randomUUID())!;
 store.update(running.id,claimed.lease,"running","generating","prompt-old");
 const queued=store.create(params(),null);
 for(let i=0;i<60;i++){
   const done=store.create(params(),null);
   store.db.prepare("UPDATE jobs SET status='completed' WHERE id=?").run(done.id);
 }
 const state=store.state();
 expect(state.jobs).toHaveLength(52);
 expect(state.jobs.find(j=>j.id===running.id)?.status).toBe("running");
 expect(state.jobs.find(j=>j.id===queued.id)?.queue_position).toBe(1);
 expect(state.queue).toEqual({active:2,limit:500});
});
test("两个连接不可同时领取；持久化后另一连接可读",()=>{
 const directory=mkdtempSync(join(tmpdir(),"comfy-queue-"));const path=join(directory,"jobs.sqlite");
 const a=new JobStore(path),b=new JobStore(path);
 try{const j=a.create(params(),null);const claimed=a.claim(randomUUID());expect(claimed?.id).toBe(j.id);expect(b.claim(randomUUID())).toBeNull();expect(b.row(j.id).status).toBe("claimed");}finally{a.db.close();b.db.close();rmSync(directory,{recursive:true});}
});
test("取消的任务不会被领取，领取后不可取消",()=>{
 const canceled=store.create(params(),null);store.cancel(canceled.id);expect(store.claim(randomUUID())).toBeNull();
 const next=store.create(params(),null);store.claim(randomUUID());expect(()=>store.cancel(next.id)).toThrow("只能取消");
});
test("必须持有效租约且经过上传状态才能完成",()=>{
 const j=store.create(params(),null),claim=store.claim(randomUUID())!;
 expect(()=>store.update(j.id,randomUUID(),"running","invalid")).toThrow("租约");
 expect(()=>store.complete(j.id,claim.lease,new Uint8Array([1]))).toThrow("仅已提交");
 store.update(j.id,claim.lease,"running","accepted","prompt-1");
 expect(()=>store.update(j.id,claim.lease,"running","changed","prompt-2")).toThrow("不可替换");
 store.update(j.id,claim.lease,"uploading","uploading","prompt-1");
 expect(store.complete(j.id,claim.lease,new Uint8Array([1])).status).toBe("completed");
 expect(store.complete(j.id,claim.lease,new Uint8Array([1])).status).toBe("completed");
});
test("过期租约进入失败终态，不会重新领取未知执行结果",()=>{
 const j=store.create(params(),null),claim=store.claim(randomUUID())!;
 store.db.prepare("UPDATE jobs SET lease_until=0 WHERE id=?").run(j.id);
 expect(store.claim(randomUUID())).toBeNull();expect(store.row(j.id).status).toBe("failed");
 expect(()=>store.complete(j.id,claim.lease,new Uint8Array([1]))).toThrow();
});
test("服务器返回队列位置，并要求图生图提供图片",()=>{
 const a=store.create(params(),null),b=store.create(params(),null);
 expect(a.queue_position).toBe(1);expect(b.queue_position).toBe(2);
 expect(()=>store.create(params({mode:"img2img"}),null)).toThrow("参考图片");
});
test("只领取在线后端支持的任务，离线视频不阻塞图片",()=>{
 const video=store.create(params({mode:"h3_t2v",width:640,height:384}),null);
 const image=store.create(params(),null);
 expect(store.claim(randomUUID(),[])===null).toBe(true);
 expect(store.claim(randomUUID(),["text","img2img"])?.id).toBe(image.id);
 expect(store.row(video.id).status).toBe("queued");
});
test("H3 首帧模式需有首帧，参考模式需有素材，纯文字无需图片",()=>{
 expect(()=>store.create(params({mode:"h3_i2v",width:640,height:384}),null)).toThrow("首帧图片");
 expect(()=>store.create(params({mode:"h3_r2v",width:640,height:384}),null)).toThrow("参考素材");
 expect(store.create(params({mode:"h3_t2v",width:640,height:384}),null).media_type).toBe("video");
});
test("多素材持久化并只允许有效租约读取，参考模式可单独使用音频",()=>{
 const j=store.create(params({mode:"h3_r2v",width:640,height:360}),null,[{key:"ref_audio_0",kind:"audio",mime:"audio/wav",name:"voice.wav",data:new Uint8Array([1,2,3])}]);
 expect(j.assets[0].kind).toBe("audio");
 const claim=store.claim(randomUUID())!;
 expect(Array.from(store.asset(j.id,claim.lease,"ref_audio_0").data)).toEqual([1,2,3]);
 expect(()=>store.asset(j.id,randomUUID(),"ref_audio_0")).toThrow("租约");
 expect(()=>store.asset(j.id,claim.lease,"ref_video_0")).toThrow("不存在");
 expect(JSON.stringify(store.state())).not.toContain('"data"');
});
test("心跳分别报告 Windows 与 Mac 的可用性",()=>{
 const id=randomUUID();store.heartbeat(id,{h3_online:true,local_online:false});
 const health=store.state().worker;expect(health?.h3_online).toBe(true);expect(health?.local_online).toBe(false);
 store.claim(id,[]);expect(store.state().worker?.h3_online).toBe(true);
});
