import { timingSafeEqual } from "node:crypto";
import { StoreError } from "./store";

// 本进程必须只监听 loopback；远程请求只通过 Tailscale Serve 进入。
export function requireLocal(request: Request) {
  if (process.env.MVP_LOCAL_ENABLED !== "1" || process.env.VERCEL) throw new StoreError("私人画室模式未启用",403);
  const host=request.headers.get("host");
  if(!host) throw new StoreError("缺少请求主机",403);
  const allowed=new Set(["http://localhost:3000","http://127.0.0.1:3000"]);
  const configuredOrigins=[process.env.MVP_ALLOWED_ORIGIN,...(process.env.MVP_ALLOWED_ORIGINS?.split(",")??[])].filter((v):v is string=>!!v?.trim());
  for(const raw of configuredOrigins) {
    const configured=new URL(raw.trim());
    if(configured.protocol!=="https:" || !configured.hostname.endsWith(".ts.net")) throw new StoreError("私网入口配置不正确",503);
    allowed.add(configured.origin);
  }
  const origins=[...allowed].filter(origin=>new URL(origin).host===host);
  if(!origins.length) throw new StoreError("仅允许本机或已配置的 Tailscale 私网入口",403);
  const origin=request.headers.get("origin"),site=request.headers.get("sec-fetch-site");
  if((origin&&!origins.includes(origin)) || site==="cross-site") throw new StoreError("不允许跨站请求",403);
  if(!["GET","HEAD"].includes(request.method)&&!origin&&!request.headers.get("authorization")) throw new StoreError("缺少请求来源",403);
}
export function requireWorker(request: Request) {
  const expected=process.env.MVP_WORKER_TOKEN,actual=request.headers.get("authorization")?.replace(/^Bearer /,"");
  if(!expected||!actual) throw new StoreError("Worker 凭证无效",401);
  const a=Buffer.from(actual),b=Buffer.from(expected);
  if(a.length!==b.length||!timingSafeEqual(a,b)) throw new StoreError("Worker 凭证无效",401);
}
export async function readLimited(request: Request, limit: number, onProgress?:(bytes:number)=>void) {
  const reader=request.body?.getReader(); if (!reader) return new Uint8Array();
  const chunks: Uint8Array[]=[]; let size=0;
  while(true) { const {done,value}=await reader.read(); if(done) break; size+=value.byteLength; onProgress?.(size); if(size>limit) { await reader.cancel(); throw new StoreError("请求文件过大",413); } chunks.push(value); }
  return new Uint8Array(Buffer.concat(chunks));
}
