import type { Job } from "./schema";

export class ApiError extends Error {
  constructor(message:string,public status:number) {super(message);}
}
export type UploadProgress = {phase:"uploading"|"validating"|"checking";loaded:number;total:number};
export const uploadTimeoutMs=15*60*1000;
export const uploadIdleMs=90*1000;

function jsonResponse(text:string,status:number):unknown {
  let data:unknown;
  try {data=JSON.parse(text);} catch {
    throw new ApiError(`服务器返回异常（HTTP ${status}），请检查私网连接后重试`,status);
  }
  if(status<200 || status>=300) {
    const error=data && typeof data==="object" && "error" in data ? data.error : null;
    throw new ApiError(typeof error==="string"?error:`请求失败（HTTP ${status}）`,status);
  }
  return data;
}

export async function api<T=unknown>(url:string,init?:RequestInit):Promise<T> {
  try {
    const response=await fetch(url,{cache:"no-store",signal:AbortSignal.timeout(15000),...init});
    return jsonResponse(await response.text(),response.status) as T;
  } catch(error) {
    if(error instanceof ApiError) throw error;
    if(error instanceof Error && ["TimeoutError","AbortError"].includes(error.name)) throw new Error("连接暂时超时，正在等待私网恢复；已提交的生成任务会继续运行");
    throw new Error("暂时无法连接创作室，请检查 Tailscale 或网络连接");
  }
}

export async function findSubmittedJob(requestId:string):Promise<Job|null> {
  try {return await api<Job>(`/api/mvp/jobs/request/${requestId}`);}
  catch(error) {if(error instanceof ApiError && error.status===404) return null;throw error;}
}

// Progress resets the inactivity timer; a slow but active upload can exceed two minutes.
export function uploadJob(form:FormData,onProgress:(p:UploadProgress)=>void):Promise<Job> {
  return new Promise((resolve,reject)=>{
    const xhr=new XMLHttpRequest();
    let idle:ReturnType<typeof setTimeout>|undefined;
    let settled=false,stalled=false,phase:UploadProgress["phase"]="uploading",loaded=0,total=0;
    const finish=(error?:Error,job?:Job)=>{
      if(settled) return;
      settled=true;clearTimeout(idle);
      if(error) reject(error);else resolve(job!);
    };
    const touch=()=>{
      if(settled) return;
      clearTimeout(idle);
      idle=setTimeout(()=>{stalled=true;xhr.abort();},uploadIdleMs);
    };
    xhr.open("POST","/api/mvp/jobs");
    xhr.timeout=uploadTimeoutMs;
    const params=JSON.parse(String(form.get("params"))) as {requestId:string};
    xhr.setRequestHeader("X-Request-Id",params.requestId);
    xhr.upload.onprogress=event=>{
      loaded=event.loaded;total=event.lengthComputable?event.total:0;
      touch();onProgress({phase,loaded,total});
    };
    xhr.upload.onload=()=>{
      phase="validating";touch();onProgress({phase,loaded:total||loaded,total});
    };
    xhr.onprogress=touch;
    xhr.onload=()=>{
      try {finish(undefined,jsonResponse(xhr.responseText,xhr.status) as Job);}
      catch(error) {finish(error instanceof Error?error:new Error("提交结果无法读取"));}
    };
    xhr.onerror=()=>finish(new Error("上传连接中断，请检查 Tailscale 或网络连接"));
    xhr.ontimeout=()=>finish(new Error("上传或素材校验超过 15 分钟，提交确认超时"));
    xhr.onabort=()=>finish(new Error(stalled?`${phase==="uploading"?"上传":"素材校验"}已连续 90 秒没有响应，连接可能中断`:"上传已中止"));
    onProgress({phase,loaded,total});touch();
    try {xhr.send(form);} catch(error) {finish(error instanceof Error?error:new Error("无法开始上传"));}
  });
}

export async function submitWithRecovery(form:FormData,onProgress:(p:UploadProgress)=>void,retry=false):Promise<Job> {
  const {requestId}=JSON.parse(String(form.get("params"))) as {requestId:string};
  if(retry) {
    onProgress({phase:"checking",loaded:0,total:0});
    const existing=await findSubmittedJob(requestId);
    if(existing) return existing;
  }
  try {return await uploadJob(form,onProgress);}
  catch(error) {
    if(error instanceof ApiError && error.status>=400 && error.status<500) throw error;
    onProgress({phase:"checking",loaded:0,total:0});
    try {const existing=await findSubmittedJob(requestId);if(existing) return existing;} catch {/* Preserve the original upload error and submission ID. */}
    const message=error instanceof Error?error.message:"提交确认失败";
    throw new Error(`${message}。请先查看最近任务；不改参数直接重试会沿用本次提交编号，避免重复创建任务。`);
  }
}
