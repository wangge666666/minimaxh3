import { z, ZodError } from "zod";
import sharp from "sharp";
import { createSchema, isVideoMode, modes } from "@/lib/mvp/schema";
import { totalAssetBytes } from "@/lib/mvp/h3";
import { parseAssets } from "@/lib/mvp/uploads";
import { getStore, StoreError } from "@/lib/mvp/store";
import { requireLocal, requireWorker, readLimited } from "@/lib/mvp/access";
import { validateMp4, mediaResponse } from "@/lib/mvp/media";
export const runtime="nodejs";
export const dynamic="force-dynamic";
const uuid=z.uuid();
const progressSchema=z.object({ id:uuid, lease:uuid, status:z.enum(["claimed","running","uploading","failed"]), message:z.string().max(500), prompt_id:z.string().min(1).max(128).optional() }).strict();
const json=(data: unknown,status=200)=>Response.json(data,{status,headers:{"Cache-Control":"no-store"}});
async function handle(request: Request, context: {params:Promise<{path?:string[]}>}) {
  try {
    requireLocal(request);
    const parts=(await context.params).path??[], action=parts.join("/"), method=request.method;
    const worker=parts[0]==="worker"; if(worker) requireWorker(request);
    const db=getStore();
    if (method==="GET" && action==="state") return json({...db.state(),features:{imageGeneration:process.env.MVP_IMAGE_GENERATION_ENABLED!=="0"}});
    if(method==="GET" && parts[0]==="jobs" && parts[1]==="request" && parts.length===3) {
      const job=db.findByRequestId(uuid.parse(parts[2]));
      if(!job) throw new StoreError("此提交尚未创建任务",404);
      return json(job);
    }
    if (["GET","HEAD"].includes(method) && parts[0]==="jobs" && ["image","media","poster"].includes(parts[2]) && parts.length===3) {
      const id=uuid.parse(parts[1]),kind=parts[2]==="poster"?"poster":"output";
      const info=db.resultInfo(id,kind);
      const video=isVideoMode(JSON.parse(info.params).mode);
      return mediaResponse({length:info.size!,read:(start,end)=>db.resultBytes(id,kind,start,end)},kind==="poster"?"image/jpeg":video?"video/mp4":"image/png",kind==="poster"?`${id}-poster`:id,request);
    }
    if (method==="GET" && parts[0]==="worker" && parts[1]==="input" && parts.length===4) {
      const asset=db.asset(uuid.parse(parts[2]),uuid.parse(request.headers.get("x-lease-id")),parts[3]);
      return new Response(new Uint8Array(asset.data),{headers:{"Content-Type":asset.mime,"Cache-Control":"no-store"}});
    }
    if (method==="GET" && parts[0]==="worker" && parts[1]==="input" && parts.length===3) {
      const row=db.owned(uuid.parse(parts[2]),uuid.parse(request.headers.get("x-lease-id")));
      if(!row.input || !["claimed","running"].includes(row.status)) throw new StoreError("参考图不可用",404);
      return new Response(new Uint8Array(row.input),{headers:{"Content-Type":"image/png","Cache-Control":"no-store"}});
    }
    if (method!=="POST") throw new StoreError("接口不存在",404);
    if (action==="jobs") {
      const started=Date.now();let bytes=0,stage="receiving";
      const submission=uuid.safeParse(request.headers.get("x-request-id")).data??null;
      console.info(JSON.stringify({event:"job_upload_started",submission}));
      try {
        const raw=await readLimited(request,totalAssetBytes+1024*1024,n=>{bytes=n;});
        stage="validating";
        const form=await new Response(raw,{headers:{"Content-Type":request.headers.get("content-type")??""}}).formData();
        const params=createSchema.parse(JSON.parse(String(form.get("params"))));
        if(submission && submission!==params.requestId) throw new StoreError("提交编号不一致",400);
        const existing=db.findByRequestId(params.requestId);
        if(!existing && !isVideoMode(params.mode) && process.env.MVP_IMAGE_GENERATION_ENABLED==="0") throw new StoreError("本站已关闭 Mac 图片生成，请使用视频创作。历史图片仍可查看和下载。",410);
        const job=existing??db.create(params,null,await parseAssets(form,params.mode));
        console.info(JSON.stringify({event:"job_upload_accepted",submission:params.requestId,job_id:job.id,bytes,elapsed_ms:Date.now()-started,reused:!!existing}));
        return json(job,201);
      } catch(error) {
        console.warn(JSON.stringify({event:"job_upload_failed",submission,bytes,stage,elapsed_ms:Date.now()-started,error_type:error instanceof Error?error.name:"unknown"}));
        throw error;
      }
    }
    if (action==="worker/complete") {
      const id=uuid.parse(request.headers.get("x-job-id")),lease=uuid.parse(request.headers.get("x-lease-id"));
      const row=db.owned(id,lease); const params=createSchema.parse(JSON.parse(row.params));
      const video=isVideoMode(params.mode);
      const multipart=video && request.headers.get("content-type")?.startsWith("multipart/form-data");
      let raw=await readLimited(request,(video?64:16)*1024*1024+(multipart?512*1024:0));
      if(video) {
        let poster:Uint8Array|null=null;
        if(multipart) {
          const form=await new Response(raw,{headers:{"Content-Type":request.headers.get("content-type")!}}).formData();
          const file=form.get("video"),cover=form.get("poster");
          if(!(file instanceof File)||file.size>64*1024*1024||!(cover instanceof File)||!cover.size||cover.size>256*1024) throw new StoreError("视频或封面格式无效",400);
          raw=new Uint8Array(await file.arrayBuffer());
          const image=sharp(Buffer.from(await cover.arrayBuffer()),{limitInputPixels:640*640});const meta=await image.metadata();
          if(meta.format!=="jpeg" || (meta.width??0)>640 || (meta.height??0)>640) throw new StoreError("封面必须是 640 像素以内的 JPEG",400);
          poster=new Uint8Array(await image.jpeg({quality:82}).toBuffer());
        }
        validateMp4(raw);return json(db.complete(id,lease,raw,poster));
      }
      const image=sharp(raw,{limitInputPixels:1000000}); const meta=await image.metadata();
      if(meta.format!=="png" || meta.width!==params.width || meta.height!==params.height) throw new StoreError("结果图片格式或尺寸不匹配",400);
      const png=await image.png().toBuffer();
      return json(db.complete(id,lease,png));
    }
    const body=JSON.parse(new TextDecoder().decode(await readLimited(request,16384)));
    if(action==="cancel") return json(db.cancel(z.object({id:uuid}).strict().parse(body).id));
    if(action==="worker/heartbeat" || action==="worker/claim") {
      const p=z.object({worker_id:uuid,h3_online:z.boolean().optional(),local_online:z.boolean().optional(),available_modes:z.array(z.enum(modes)).max(5).optional()}).strict().parse(body);
      if(action.endsWith("heartbeat")) { db.heartbeat(p.worker_id,p); return json({ok:true}); }
      const available=process.env.MVP_IMAGE_GENERATION_ENABLED==="0"?(p.available_modes??modes).filter(isVideoMode):p.available_modes;
      return json({job:db.claim(p.worker_id,available)});
    }
    if(action==="worker/progress") { const p=progressSchema.parse(body); return json(db.update(p.id,p.lease,p.status,p.message,p.prompt_id)); }
    throw new StoreError("接口不存在",404);
  } catch(error) {
    if(error instanceof StoreError) return json({error:error.message},error.status);
    if(error instanceof ZodError) return json({error:error.issues.map(i=>`${i.path.join(".")}: ${i.message}`).join("；")},400);
    if(error instanceof SyntaxError || error instanceof TypeError) return json({error:"请求格式不正确"},400);
    // 图像解码错误不回显内部路径与原始异常。
    return json({error:"操作失败，请检查图片格式或查看本地服务日志"},400);
  }
}
export const GET=handle;
export const HEAD=handle;
export const POST=handle;
