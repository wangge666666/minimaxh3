"use client";
import { useEffect, useRef, useState } from "react";
import type { WorkflowEngine } from "@hub/shared";
import { nativeDefaults, nativeLimits, workflowOption, type WorkflowOption } from "@/lib/mvp/workflow-options";
import { Button } from "@/components/ui/button";
import { ReferencePicker } from "@/components/reference-picker";
import { VideoPlayer } from "@/components/video-player";
import { api, submitWithRecovery, type UploadProgress } from "@/lib/mvp/client";
import { isVideoMode, needsReference, type Job, type Mode } from "@/lib/mvp/schema";
import { maxActiveJobs, recentHistoryLimit } from "@/lib/mvp/queue";
import { ratios, resolutions, videoSize, nativeSize, duration, framesForDuration, inputDurationForFrames, totalAssetBytes, type Ratio, type AssetKind } from "@/lib/mvp/h3";

type State = { jobs: Job[]; worker: { online: boolean; h3_online: boolean; local_online: boolean } | null; features?: {imageGeneration:boolean}; queue?: {active:number;limit:number}; workflows?: WorkflowOption[] };
const labels: Record<string, string> = { queued: "排队中", claimed: "已领取", running: "生成中", uploading: "验证与保存", completed: "已完成", failed: "失败 · 需检查", canceled: "已取消" };
const names: Record<Mode, string> = { text: "文生图", img2img: "图片重绘", h3_t2v: "文生视频", h3_i2v: "首尾帧", h3_r2v: "多素材参考" };
const field = "w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm outline-none focus:ring-2 focus:ring-primary";

export default function Studio() {
  const [data, setData] = useState<State>({ jobs: [], worker: null });
  const [mode, setMode] = useState<Mode>("h3_i2v");
  const [workflowEngine, setWorkflowEngine] = useState<WorkflowEngine>("native");
  const option = workflowOption(data.workflows, mode, workflowEngine);
  const limits = option?.limits ?? nativeLimits;
  const workflowReady = !isVideoMode(mode) || (option?.ready ?? workflowEngine === "native");
  const [prompt, setPrompt] = useState("");
  const [size, setSize] = useState("256x256");
  const [denoise, setDenoise] = useState(0.6);
  const [seed, setSeed] = useState("");
  const [files, setFiles] = useState<Record<string,File[]>>({});
  const [ratio,setRatio]=useState<Ratio>("16:9");
  const [resolution,setResolution]=useState(360);
  const [durationSeconds,setDurationSeconds]=useState(String(nativeDefaults.durationSeconds));
  const durationValue=Number(durationSeconds);
  const validDuration=durationSeconds.trim()!=="" && Number.isFinite(durationValue) && durationValue>=limits.minDurationSeconds && durationValue<=limits.maxDurationSeconds;
  const frames=validDuration?framesForDuration(durationValue):124;
  const [steps,setSteps]=useState(nativeDefaults.steps);
  const [sound,setSound]=useState(true);
  const [referenceVideoAudio,setReferenceVideoAudio]=useState(true);
  const [refImageSize,setRefImageSize]=useState<"match"|"max">("match");
  const [busy, setBusy] = useState(false);
  const [uploadProgress,setUploadProgress]=useState<UploadProgress|null>(null);
  const [error, setError] = useState("");
  const [connection, setConnection] = useState("正在连接");
  const [selected, setSelected] = useState<string | null>(null);
  const requestId = useRef<string | null>(null);
  const pendingSeed = useRef<number | null>(null);
  const video = isVideoMode(mode);
  const imageGenerationEnabled = data.features?.imageGeneration===true;
  const reference = needsReference(mode);
  const active = data.queue?.active ?? data.jobs.filter(j => ["queued", "claimed", "running", "uploading"].includes(j.status)).length;
  const queueLimit = data.queue?.limit ?? maxActiveJobs;
  const job = data.jobs.find(j => j.id === selected) ?? data.jobs[0];
  const [outputWidth,outputHeight]=videoSize(ratio,resolution);
  const [canvasWidth,canvasHeight]=nativeSize(outputWidth,outputHeight);
  function groups(): [string,AssetKind,number,string,string?][] {
    if(mode==="img2img") return [["reference","image",1,"参考图片"]];
    if(mode==="h3_i2v") return [["first_frame","image",1,"首帧图片（必选）"],["last_frame","image",1,"尾帧图片（可选）"]];
    if(mode==="h3_r2v") return [["ref_image","image",9,"参考图片","Picture"],["ref_video","video",3,"参考视频","Video"],["ref_audio","audio",3,"参考音频",referenceVideoAudio && files.ref_video?.length?undefined:"Audio"]];
    return [];
  }

  useEffect(() => {
    let live = true, refreshing = false;
    const refresh = async () => {
      if (refreshing) return;
      refreshing = true;
      try { const next = await api<State>("/api/mvp/state"); if (live) { setData(next); setConnection("私网队列已连接"); } }
      catch (e) { if (live) setConnection(e instanceof Error ? e.message : "连接失败"); }
      finally { refreshing = false; }
    };
    void refresh(); const interval = setInterval(refresh, 2500);
    return () => { live = false; clearInterval(interval); };
  }, []);
  function changed() { requestId.current = null; pendingSeed.current = null; }
  function selectMode(next: Mode) { setMode(next); setError(""); changed(); }
  function toggleTheme() {
    const current = document.documentElement.dataset.theme ?? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    document.documentElement.dataset.theme = current === "dark" ? "light" : "dark";
  }
  async function submit(event: React.FormEvent) {
    event.preventDefault(); setError("");
    if(!workflowReady) {setError(option?.reason ?? "导演台尚未就绪，请选择原生生成方式");return;}
    if(video && !validDuration) {setError("请输入 4–15 秒之间的时长，可包含小数");return;}
    const attachments=groups().flatMap(([key])=>(files[key]??[]).map((file,index)=>({key:key.startsWith("ref_")?`${key}_${index}`:key,file})));
    if(reference && (mode==="h3_r2v" ? !attachments.length : !(files[mode==="h3_i2v"?"first_frame":"reference"]?.length))) {setError(mode==="h3_r2v"?"请至少上传一项图片、视频或音频参考":"请先选择参考图片或首帧");return;}
    if(attachments.reduce((sum,a)=>sum+a.file.size,0)>totalAssetBytes) {setError("单次参考素材合计不能超过 96 MB");return;}
    setBusy(true);
    try {
      const [width, height] = video ? [outputWidth,outputHeight] : size.split("x").map(Number);
      const actualSeed = seed === "" ? (pendingSeed.current ??= crypto.getRandomValues(new Uint32Array(1))[0]) : Number(seed);
      const retry=requestId.current!==null;
      requestId.current ??= crypto.randomUUID();
      const form = new FormData();
      form.set("params", JSON.stringify({ requestId: requestId.current, mode, prompt, width, height, seed: actualSeed, denoise, ...(video ? { workflowEngine,durationSeconds:durationValue,frames, fps: 24,steps,sound,referenceVideoAudio,refImageSize } : {}) }));
      for(const attachment of attachments) form.set(attachment.key,attachment.file);
      const created = await submitWithRecovery(form,setUploadProgress,retry);
      requestId.current = null; pendingSeed.current = null; setSelected(created.id);
      setData(previous => ({ ...previous, jobs: [created, ...previous.jobs.filter(j => j.id !== created.id)] }));
    } catch (e) { setError(e instanceof Error ? e.message : "提交失败"); }
    finally { setBusy(false);setUploadProgress(null); }
  }
  async function cancel(id: string) {
    try {
      const result = await api<Job>("/api/mvp/cancel", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id }) });
      setData(previous => ({ ...previous, jobs: previous.jobs.map(j => j.id === id ? result : j) }));
    } catch (e) { setError(e instanceof Error ? e.message : "取消失败"); }
  }
  function reuse(item: Job) {
    if(!isVideoMode(item.mode) && !imageGenerationEnabled) return;
    setPrompt(item.prompt); setMode(item.mode); setWorkflowEngine(item.workflowEngine??"native"); setSeed(String(item.seed)); setDenoise(item.denoise);
    if (!isVideoMode(item.mode)) setSize(`${item.width}x${item.height}`);
    else {setRatio(item.width===item.height?"1:1":item.width>item.height?"16:9":"9:16");setResolution(resolutions.includes(Math.min(item.width,item.height) as 360)?Math.min(item.width,item.height):360);setDurationSeconds(String(item.durationSeconds??inputDurationForFrames(item.frames??124)));setSteps(item.steps??20);setSound(item.sound??true);setReferenceVideoAudio(item.referenceVideoAudio??true);setRefImageSize(item.refImageSize??"match");}
    setFiles({});
    setError(needsReference(item.mode) ? "参数已填入，请重新选择参考素材。" : ""); changed();
  }

  return <main className="min-h-screen bg-background text-foreground">
    <header className="border-b border-border bg-card"><div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-5 py-5">
      <a href="/" className="text-lg font-semibold tracking-tight">◈ <span className="text-primary">私人创作室</span></a>
      <div className="flex items-center gap-4"><span className="rounded-full bg-muted px-3 py-1 text-xs">Tailscale · 私网访问</span><button type="button" className="text-sm opacity-70" onClick={toggleTheme} aria-label="切换深浅色">◐ 切换主题</button></div>
    </div></header>
    <div className="mx-auto max-w-7xl px-5 py-8">
      <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
        <div><p className="text-xs font-medium tracking-widest text-primary">{imageGenerationEnabled?"MINIMAX H3 + Z-IMAGE":"MINIMAX H3"} / 私人创作空间</p><h1 className="mt-2 text-3xl font-semibold">让想法成画，让画面动起来。</h1><p className="mt-3 text-sm opacity-60">{imageGenerationEnabled?"Windows 生成视频，Mac 生成图片。":"视频由 G58 本机生成，参考素材与结果都保存在 G58。"}提交后可关闭页面，稍后回来查看结果。</p></div>
        <div className="space-y-2 text-xs" aria-live="polite">
          <p className={data.worker?.h3_online ? "text-emerald-500" : "text-amber-500"}>● Windows · MiniMax H3 {data.worker?.h3_online ? "在线" : "离线，视频任务将等待"}</p>
          {imageGenerationEnabled && <p className={data.worker?.local_online ? "text-emerald-500" : "text-amber-500"}>● Mac · Z-Image {data.worker?.local_online ? "在线" : "离线，图片任务将等待"}</p>}
          <p className="opacity-50">{connection} · {active}/{queueLimit} 个未完成任务</p>
        </div>
      </div>
      <div className="grid min-w-0 gap-6 lg:grid-cols-[380px_minmax(0,1fr)]">
        <form onSubmit={submit} className="min-w-0 space-y-5 rounded-2xl border border-border bg-card p-6 self-start">
          {imageGenerationEnabled && <div className="grid grid-cols-2 gap-2 rounded-xl bg-background p-1" role="group" aria-label="创作类型">
            <button type="button" disabled={busy} aria-pressed={video} onClick={() => selectMode("h3_i2v")} className={`rounded-lg px-3 py-2 text-sm ${video ? "bg-primary text-primary-foreground" : "opacity-60"}`}>视频创作</button>
            <button type="button" disabled={busy} aria-pressed={!video} onClick={() => selectMode("text")} className={`rounded-lg px-3 py-2 text-sm ${!video ? "bg-primary text-primary-foreground" : "opacity-60"}`}>图片创作</button>
          </div>}
          <div><h2 className="font-semibold">{video ? "MiniMax H3" : "Z-Image Turbo"}</h2><p className="mt-1 text-xs opacity-50">{video ? `${outputWidth} × ${outputHeight} · ${validDuration?`预计 ${duration(frames)} 秒`:"请填写时长"} · 24 fps` : "每次 1 张 · Mac 计算，G58 保存"}</p></div>
          <div className={`grid gap-2 ${video ? "grid-cols-3" : "grid-cols-2"}`} role="group" aria-label="生成模式">
            {(video ? (["h3_i2v", "h3_r2v", "h3_t2v"] as Mode[]) : (["text", "img2img"] as Mode[])).map(value => <button type="button" key={value} disabled={busy} aria-pressed={mode === value} onClick={() => selectMode(value)} className={`rounded-lg border px-2 py-2 text-xs ${mode === value ? "border-primary bg-primary/10 text-primary" : "border-border"}`}>{names[value]}</button>)}
          </div>
          {video && <p className="text-xs leading-relaxed opacity-60">{mode === "h3_i2v" ? "上传首帧，可再添加尾帧，描述画面如何运动和过渡。" : mode === "h3_r2v" ? "组合图片、视频与音频参考，描述要保留的外观、动作或声音。" : "描述画面、动作、镜头与声音，无需上传图片。"}</p>}
          {video && <fieldset className="space-y-2"><legend className="mb-2 text-sm font-medium">生成方式</legend>
            <div className="grid grid-cols-2 gap-2">{(["native","director"] as const).map(engine => <button key={engine} type="button" disabled={busy} aria-pressed={workflowEngine===engine} aria-describedby="workflow-status" onClick={()=>{setWorkflowEngine(engine);setError("");changed();}} className={`rounded-lg border px-3 py-2 text-sm ${workflowEngine===engine?"border-primary bg-primary/10 text-primary":"border-border"}`}>{engine==="native"?"原生（默认）":`导演台${workflowOption(data.workflows,mode,engine)?.ready?"":" · 未就绪"}`}</button>)}</div>
            <p id="workflow-status" role="status" className={`text-xs leading-relaxed ${workflowReady?"opacity-60":"text-amber-600 dark:text-amber-400"}`}>{workflowReady ? (workflowEngine==="native"?"使用原生流程，默认 20 步。切换生成方式会保留当前参数和素材。":"导演台已就绪。") : (option?.reason??"导演台尚未就绪，正在等待工作流交付与验收")}</p>
          </fieldset>}
          {video && <div className="space-y-4 border-y border-border py-4">
            <fieldset><legend className="mb-2 text-sm font-medium">画面比例</legend><div className="grid grid-cols-3 gap-2">{ratios.filter(value=>limits.ratios.includes(value)).map(value=><button key={value} disabled={busy} type="button" aria-pressed={ratio===value} onClick={()=>{setRatio(value);changed();}} className={`flex items-center justify-center gap-2 rounded-lg border px-2 py-3 text-xs ${ratio===value?"border-primary bg-primary/10 text-primary":"border-border"}`}><span className={`inline-block border border-current ${value==="1:1"?"h-4 w-4":value==="16:9"?"h-3 w-5":"h-5 w-3"}`}/>{value}</button>)}</div></fieldset>
            <div className="grid grid-cols-2 gap-3">
              <div><label htmlFor="resolution" className="text-sm">分辨率</label><select id="resolution" disabled={busy} value={resolution} className={`${field} mt-2`} onChange={e=>{setResolution(Number(e.target.value));changed();}}>{resolutions.filter(value=>limits.resolutions.includes(value)).map(value=>{const [w,h]=videoSize(ratio,value);return <option key={value} value={value}>{value===360?"预览":value===576?"标清":"高清"} · {w} × {h}</option>;})}</select></div>
              <div><label htmlFor="duration" className="text-sm">视频时长（秒）</label><input id="duration" type="number" required min={limits.minDurationSeconds} max={limits.maxDurationSeconds} step="any" aria-describedby="duration-help" disabled={busy} value={durationSeconds} placeholder="4–15，可输入小数" className={`${field} mt-2`} onChange={e=>{setDurationSeconds(e.target.value);changed();}}/></div>
            </div>
            <p id="duration-help" className="text-xs leading-relaxed opacity-60" aria-live="polite">{validDuration?`实际生成约 ${duration(frames)} 秒（${frames} 帧）。模型按 24 fps、17k+5 帧向上取整。`:"请输入 4–15 秒，可包含小数，例如 6 或 7.5。"}</p>
            {validDuration && frames<124 && <p className="text-xs leading-relaxed text-amber-600 dark:text-amber-400">此时长低于官方约 5–15 秒的训练范围，生成效果需要实测。</p>}
            <p className="text-xs leading-relaxed opacity-50">建议先用预览尺寸、输入 5 秒（实际约 5.17 秒）。高清、长视频和多素材更耗显存，请逐步增加。</p>
          </div>}
          {groups().map(([key,kind,max,label,tag])=><ReferencePicker key={key} id={key} kind={kind} label={label} max={max} tag={tag} disabled={busy} files={files[key]??[]} onError={setError} onChange={next=>{setFiles(previous=>({...previous,[key]:next}));setError("");changed();}}/>)}
          {mode==="h3_i2v" && <p className="text-xs leading-relaxed opacity-50">首尾帧将居中裁剪以适应画面，请把主体放在中央。</p>}
          {mode==="h3_r2v" && <div className="space-y-3 rounded-xl bg-background p-3 text-xs leading-relaxed">
            <p className="opacity-60">图片用 &lt;Picture 1&gt;、视频用 &lt;Video 1&gt; 指代。音频编号先计算启用的参考视频原声，再计算独立音频。素材会按列表顺序编号，合计最多 96 MB。</p>
            <label className="flex items-center gap-2"><input type="checkbox" checked={referenceVideoAudio} disabled={busy} onChange={e=>{setReferenceVideoAudio(e.target.checked);changed();}} className="accent-primary"/>同时参考视频原声</label>
            <p className="opacity-50">参考片段从开头使用，视频最多取本次生成时长。声音是生成参考，不能保证逐字对白或精确复刻。</p>
          </div>}
          <div><label htmlFor="prompt" className="text-sm font-medium">提示词</label><textarea id="prompt" placeholder={video ? "描述画面、人物动作、镜头运动，以及对白或环境声音…" : "描述画面、风格、光线，以及希望对参考图做的改变…"} required maxLength={2000} rows={5} value={prompt} disabled={busy} onChange={e => { setPrompt(e.target.value); changed(); }} className={`${field} mt-2 resize-y`} /><p className="mt-1 text-right text-xs opacity-40">{prompt.length}/2000</p></div>
          <div className={`grid gap-3 ${video ? "grid-cols-1" : "grid-cols-2"}`}>
            {!video && <div><label htmlFor="size" className="text-sm">输出尺寸</label><select id="size" className={`${field} mt-2`} disabled={busy} value={size} onChange={e => { setSize(e.target.value); changed(); }}><option value="256x256">256 × 256（测试）</option><option value="512x512">512 × 512</option><option value="512x768">512 × 768</option><option value="768x512">768 × 512</option><option value="768x768">768 × 768</option></select></div>}
            <div><label htmlFor="seed" className="text-sm">随机种子</label><input id="seed" type="number" min="0" max="4294967295" step="1" placeholder="留空随机" disabled={busy} value={seed} onChange={e => { setSeed(e.target.value); changed(); }} className={`${field} mt-2`} /></div>
          </div>
          {mode === "img2img" && <div><label htmlFor="denoise" className="flex justify-between text-sm"><span>重绘幅度</span><span className="text-primary">{denoise.toFixed(2)}</span></label><input id="denoise" className="mt-3 w-full accent-primary" type="range" min="0.1" max="1" step="0.05" value={denoise} disabled={busy} onChange={e => { setDenoise(Number(e.target.value)); changed(); }} /><div className="flex justify-between text-xs opacity-50"><span>保留原图</span><span>更多变化</span></div></div>}
          {video && <details className="rounded-xl border border-border p-3"><summary className="cursor-pointer text-sm font-medium">更多生成设置</summary><div className="mt-4 space-y-4">
            <div className="grid grid-cols-2 gap-3"><div><label htmlFor="steps" className="text-sm">采样步数</label><select id="steps" disabled={busy} value={steps} className={`${field} mt-2`} onChange={e=>{setSteps(Number(e.target.value));changed();}}>{limits.steps.map(value=><option key={value} value={value}>{value} 步{value===20?"（默认）":""}</option>)}</select></div><div><label htmlFor="fps" className="text-sm">帧率</label><select id="fps" disabled className={`${field} mt-2`}><option>24 fps（模型原生）</option></select></div></div>
            <label className="flex items-center gap-2 text-sm"><input disabled={busy} type="checkbox" checked={sound} onChange={e=>{setSound(e.target.checked);changed();}} className="accent-primary"/>保留成品声音</label><p className="text-xs opacity-50">关闭后导出静音 MP4，模型仍联合生成画面与声音。</p>
            {mode==="h3_r2v" && <div><label htmlFor="reference-detail" className="text-sm">参考图细节</label><select id="reference-detail" disabled={busy} value={refImageSize} onChange={e=>{setRefImageSize(e.target.value as "match"|"max");changed();}} className={`${field} mt-2`}><option value="match">匹配生成尺寸（默认）</option><option value="max">更多原图细节（更耗显存）</option></select></div>}
            <p className="text-xs leading-relaxed opacity-50">成品 {outputWidth} × {outputHeight}；生成画布 {canvasWidth} × {canvasHeight}，完成后居中裁剪边缘以保持所选比例。</p>
          </div></details>}
          {error && <p role="alert" className="rounded-lg bg-red-500/10 p-3 text-sm text-red-500">{error}</p>}
          {busy && uploadProgress && <div role="status" className="space-y-2 rounded-xl bg-primary/5 p-3 text-xs">
            <p>{uploadProgress.phase==="checking"?"正在确认是否已创建任务，避免重复提交…":uploadProgress.phase==="validating"?"素材已上传，正在校验并创建任务…":uploadProgress.total?`正在上传 ${Math.min(100,Math.round(uploadProgress.loaded/uploadProgress.total*100))}% · ${(uploadProgress.loaded/1024/1024).toFixed(1)} / ${(uploadProgress.total/1024/1024).toFixed(1)} MB`:"正在连接并上传…"}</p>
            {uploadProgress.phase==="uploading" && uploadProgress.total>0 && <progress className="h-2 w-full accent-primary" aria-label="参考素材上传进度" max={uploadProgress.total} value={uploadProgress.loaded}/>}
            <p className="opacity-60">上传期间请保持此页面打开。任务进入队列后可关闭页面。</p>
          </div>}
          <Button className="w-full py-3" disabled={busy || !workflowReady || active >= queueLimit}>{busy ? "正在上传并提交…" : !workflowReady ? "所选生成方式尚未就绪" : video ? "开始生成视频 →" : "开始生成图片 →"}</Button>
          <p className="text-xs leading-relaxed opacity-45">{video ? "视频按顺序生成；如果 Windows 离线，任务会保留在队列中。" : "Mac 首次加载模型可能较慢，建议先用小尺寸测试。"}</p>
        </form>
        <div className="min-w-0 space-y-6">
          <section className="rounded-2xl border border-border bg-card p-6">
            <div className="mb-5 flex items-center justify-between"><h2 className="font-semibold">生成结果</h2>{job && <span className="rounded-full bg-muted px-3 py-1 text-xs">{labels[job.status]}</span>}</div>
            <div className="flex min-h-80 items-center justify-center rounded-xl bg-background p-4">
              {job?.status === "completed" ? (isVideoMode(job.mode) ? <VideoPlayer key={job.id} id={job.id} prompt={job.prompt} width={job.width} height={job.height} hasPoster={job.has_poster}/> : <img src={`/api/mvp/jobs/${job.id}/media`} alt={job.prompt} className="max-h-[520px] max-w-full rounded-lg object-contain" />) : <div className="max-w-md text-center"><span className="text-5xl text-primary/50">◈</span><p className="mt-5 font-medium">{job ? labels[job.status] : "你的第一段创作，从这里开始"}</p><p className="mt-3 text-sm leading-relaxed opacity-60">{job?.message || (job?.status === "queued" ? `待领取队列第 ${job.queue_position} 位` : "选择模式，写下描述，开始创作。")}</p></div>}
            </div>
            {job && <div className="mt-4 flex flex-wrap items-center justify-between gap-3"><p className="max-w-md text-xs opacity-60">{names[job.mode]}{isVideoMode(job.mode)?` · ${job.workflowEngine==="director"?"导演台":"原生"}`:""} · {job.width} × {job.height}{isVideoMode(job.mode) ? ` · ${job.status==="completed"?"实际":"预计"} ${duration(job.frames)} 秒 · ${job.sound===false?"静音":"带声音"}` : ""}<br />{job.durationSeconds!==undefined && <span>请求 {job.durationSeconds} 秒 · </span>}<span className="mt-1 inline-block opacity-70">种子 {job.seed}</span></p>{job.status === "completed" && <Button asChild><a href={`/api/mvp/jobs/${job.id}/media`} download={`${job.id}.${isVideoMode(job.mode)?"mp4":"png"}`}>{isVideoMode(job.mode) ? "下载 MP4 ↓" : "下载 PNG ↓"}</a></Button>}</div>}
          </section>
          <section className="rounded-2xl border border-border bg-card p-6"><div className="mb-4 flex justify-between"><h2 className="font-semibold">任务记录</h2><span className="text-xs opacity-50">全部未完成 · 最近 {recentHistoryLimit} 条历史</span></div>
            {!data.jobs.length ? <p className="py-8 text-center text-sm opacity-50">还没有任务，提交后会显示真实进度。</p> : <ul className="divide-y divide-border">{data.jobs.map(item => <li key={item.id} className={`flex items-center gap-3 py-4 ${job?.id === item.id ? "text-primary" : ""}`}><button type="button" onClick={() => setSelected(item.id)} className="min-w-0 flex-1 text-left"><p className="truncate text-sm font-medium">{item.prompt}</p><p className="mt-1 text-xs opacity-60">{names[item.mode]}{isVideoMode(item.mode)?` · ${item.workflowEngine==="director"?"导演台":"原生"}`:""} · {labels[item.status]}{item.queue_position ? ` · 第 ${item.queue_position} 位` : ""} · {new Date(item.created_at).toLocaleString("zh-CN")}</p>{item.status === "failed" && <p className="mt-2 text-xs text-red-500">{item.message}</p>}</button>{(isVideoMode(item.mode)||imageGenerationEnabled) && <button type="button" disabled={busy} className="shrink-0 text-xs underline opacity-70 disabled:opacity-30" onClick={() => reuse(item)}>再次使用</button>}{item.status === "queued" && <button type="button" className="shrink-0 text-xs opacity-60" onClick={() => void cancel(item.id)}>取消</button>}</li>)}</ul>}
          </section>
        </div>
      </div>
      <footer className="mt-8 text-xs leading-relaxed opacity-45">仅供你的 Tailscale 私网设备访问。网页、队列、参考素材和结果保存在 DESKTOP-G58BAN7，视频由本机 MiniMax H3 生成。请保持 G58 开机联网。{imageGenerationEnabled?"图片由 Mac 的 Z-Image 计算，图片任务还需 Mac 在线。":"Mac 图片生成已关闭，历史图片仍可查看和下载。"}<br/>Powered by MiniMax H3</footer>
    </div>
  </main>;
}
