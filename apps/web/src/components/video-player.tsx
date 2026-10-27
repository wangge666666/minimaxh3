"use client";
import { useEffect, useRef, useState } from "react";

export function VideoPlayer({id,prompt,width,height,hasPoster}: {id:string;prompt:string;width:number;height:number;hasPoster:boolean}) {
  const video=useRef<HTMLVideoElement>(null);
  const [phase,setPhase]=useState<"loading"|"ready"|"buffering"|"error">("loading");
  const [slow,setSlow]=useState(false);
  useEffect(()=>{
    if(phase!=="loading" && phase!=="buffering") {setSlow(false);return;}
    const timer=setTimeout(()=>setSlow(true),8000);
    return()=>clearTimeout(timer);
  },[phase]);
  function retry() {setSlow(false);setPhase("loading");video.current?.load();}
  return <div className="w-full space-y-2">
    <div className="relative overflow-hidden rounded-lg bg-black/10">
      <video ref={video} controls playsInline preload="auto" width={width} height={height}
        poster={hasPoster?`/api/mvp/jobs/${id}/poster`:undefined} src={`/api/mvp/jobs/${id}/media`}
        className="max-h-[520px] w-full rounded-lg object-contain" aria-label={prompt}
        onLoadedData={()=>setPhase("ready")} onCanPlay={()=>setPhase("ready")} onPlaying={()=>setPhase("ready")}
        onWaiting={()=>setPhase("buffering")} onError={()=>setPhase("error")}>浏览器不支持视频播放，请下载 MP4。</video>
      {(phase==="loading" || phase==="buffering") && <div className="pointer-events-none absolute inset-x-3 top-3 text-center"><span role="status" className="inline-block rounded-full bg-black/70 px-3 py-1.5 text-xs text-white">{phase==="loading"?"正在准备播放…":"正在缓冲…"}</span></div>}
    </div>
    {(slow || phase==="error") && <div role="status" className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-muted px-3 py-2 text-xs"><span>{phase==="error"?"视频暂时无法播放":"网络加载较慢，可以重试或下载观看"}</span><button type="button" onClick={retry} className="shrink-0 text-primary underline">重新加载</button></div>}
  </div>;
}
