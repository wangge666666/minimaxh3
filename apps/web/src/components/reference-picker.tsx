"use client";
import { useEffect, useState } from "react";
import { assetLimits, type AssetKind } from "@/lib/mvp/h3";

function Preview({file,kind}: {file:File;kind:AssetKind}) {
  const [url,setUrl]=useState("");
  useEffect(()=>{const next=URL.createObjectURL(file);setUrl(next);return()=>URL.revokeObjectURL(next);},[file]);
  if(!url) return null;
  if(kind==="image") return <img src={url} alt={file.name} className="h-24 w-full rounded-lg object-contain bg-background" />;
  if(kind==="video") return <video src={url} controls preload="metadata" className="max-h-32 w-full rounded-lg" />;
  return <audio src={url} controls preload="metadata" className="h-9 w-full" />;
}
export function ReferencePicker({id,label,kind,files,max,disabled,onChange,onError,tag}: {
  id:string;label:string;kind:AssetKind;files:File[];max:number;disabled:boolean;
  onChange:(files:File[])=>void;onError:(message:string)=>void;tag?:string;
}) {
  const accept={image:"image/png,image/jpeg,image/webp",video:"video/mp4,video/webm,.mov",audio:"audio/wav,audio/mpeg,audio/mp4,audio/flac,audio/ogg,.m4a,.mp3,.wav,.flac,.ogg"}[kind];
  return <div className="space-y-2">
    <label htmlFor={id} className="flex justify-between text-sm font-medium"><span>{label}</span><span className="text-xs opacity-50">{files.length}/{max}</span></label>
    {files.map((file,index)=><div key={`${file.name}-${index}`} className="space-y-2 rounded-xl border border-border bg-background p-3">
      <div className="flex justify-between gap-2 text-xs"><span className="min-w-0 truncate">{tag ? `<${tag} ${index+1}> · ` : ""}{file.name}</span><button disabled={disabled} type="button" className="shrink-0 underline opacity-60" onClick={()=>onChange(files.filter((_,i)=>i!==index))}>移除</button></div>
      <Preview file={file} kind={kind}/>
    </div>)}
    {files.length<max && <input id={id} type="file" accept={accept} multiple={max>1} disabled={disabled} className="w-full rounded-xl border border-dashed border-border p-3 text-xs file:mr-2 file:rounded-md file:border-0 file:bg-muted file:px-3 file:py-2" onChange={event=>{
      const selected=Array.from(event.target.files??[]); event.target.value="";
      if(files.length+selected.length>max) {onError(`最多可选择 ${max} 个${label}`);return;}
      if(selected.some(f=>f.size>assetLimits[kind]*1024*1024)) {onError(`每个${label}最大 ${assetLimits[kind]} MB`);return;}
      onChange([...files,...selected]);
    }}/>}
    <p className="text-xs leading-relaxed opacity-50">{kind==="image"?"PNG / JPEG / WebP · 每张 8 MB、1600 万像素以内":kind==="video"?"MP4 / MOV / WebM · 每段 2–15 秒、20 MB 以内":"WAV / MP3 / M4A / FLAC / OGG · 每段 0.1–15 秒、10 MB 以内"}</p>
  </div>;
}
