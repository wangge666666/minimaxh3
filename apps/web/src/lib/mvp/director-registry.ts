import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { z } from "zod";
import { videoModes, type VideoMode } from "./workflow-options";

const revision = "director-v1.0.0";
const digest = z.string().regex(/^[0-9a-f]{64}$/);
const capability = z.object({
  available: z.boolean(), revision: z.literal(revision), template: z.string(), mapping: z.string(),
  fileSha256: z.record(z.string(), digest), outputNodeIds: z.tuple([z.literal("8")]),
  validation: z.object({ level: z.string(), evidence: z.string(), profiles: z.array(z.object({caseId:z.string()})) }),
});
const registrySchema = z.object({
  schemaVersion: z.literal(1), defaultEngine: z.literal("native"),
  engines: z.object({director:z.object({
    revision:z.literal(revision), status:z.literal("gpu-validated"),
    builderFilesSha256:z.record(z.string(),digest),
    modes:z.object({h3_t2v:capability,h3_i2v:capability,h3_r2v:capability}),
    runtime:z.object({requiredCustomNodes:z.array(z.string()).min(3),requiredBuiltinNodes:z.array(z.string()).min(1)}),
  })}),
  defaults:z.object({steps:z.literal(20),durationSeconds:z.literal(5)}),
  parameters:z.object({
    fps:z.literal(24),steps:z.array(z.number().int()).min(1),
    durationSeconds:z.object({min:z.number(),max:z.number()}),
    dimensions:z.array(z.tuple([z.number().int(),z.number().int()])),frames:z.array(z.number().int()),
    ratios:z.array(z.string()),resolutions:z.array(z.number()),
    refImageSize:z.array(z.string()),seed:z.object({min:z.number(),max:z.number()}),
  }),
});
type Registry = z.infer<typeof registrySchema>;
type NodeInfo = Record<string,{input?:{required?:Record<string,unknown[]>;optional?:Record<string,unknown[]>}}>;
type Probe = { endpoint:string; expires:number; info:NodeInfo|null };
let probe:Probe|undefined;
let pending: {endpoint:string; request:Promise<void>}|undefined;
const read = (path:string) => readFileSync(path,"utf8").replace(/\r\n/g,"\n");
const hash = (source:string) => createHash("sha256").update(source).digest("hex");

function loadRegistry(directory:string):Registry {
  try { return registrySchema.parse(JSON.parse(read(resolve(directory,"h3_capabilities.json")))); }
  catch { throw new Error("导演台能力包缺失或格式不正确"); }
}

function installed(directory:string,mode:VideoMode) {
  const registry=loadRegistry(directory),engine=registry.engines.director,cap=engine.modes[mode];
  if(!cap.available || cap.validation.level!=="gpu-smoke" || !cap.validation.profiles.length) throw new Error("导演台模式尚未验收");
  const stem=mode.replace("h3_","h3_director_");
  if(cap.template!==`${stem}_api.json` || cap.mapping!==`${stem}_mapping.json` || cap.validation.evidence!=="validation/director-v1.0.0.json") throw new Error("导演台固定文件契约不正确");
  try {
    const sources=[cap.template,cap.mapping].map(name=>{
      const source=read(resolve(directory,name));
      if(hash(source)!==cap.fileSha256[name]) throw new Error();
      return JSON.parse(source);
    });
    const [graph,mapping]=sources;
    if(mapping.version!=="1" || mapping.revision!==revision || mapping.template!==cap.template || JSON.stringify(mapping.outputs)!=='["8"]' || graph["8"]?.class_type!=="SaveVideo") throw new Error();
    const builder=resolve(/* turbopackIgnore: true */ process.env.MVP_DIRECTOR_BUILDER_DIRECTORY || resolve(process.cwd(),"../worker/src/comfy_hub_worker"));
    const files=["mapping.py","director_workflow.py","director_contract.py"];
    if(Object.keys(engine.builderFilesSha256).sort().join()!==files.sort().join()) throw new Error();
    for(const name of files) if(hash(read(resolve(builder,name)))!==engine.builderFilesSha256[name]) throw new Error();
    const evidence=JSON.parse(read(resolve(directory,cap.validation.evidence)));
    if(evidence.schemaVersion!==1 || evidence.revision!==revision || !Array.isArray(evidence.releaseAcceptanceCases)) throw new Error();
    for(const profile of cap.validation.profiles) {
      if(!evidence.releaseAcceptanceCases.some((item:{caseId?:string;mode?:string;passed?:boolean})=>item.caseId===profile.caseId && item.mode===mode && item.passed===true)) throw new Error();
    }
    return {registry,cap,graph};
  } catch { throw new Error("导演台工作流、构图层或验收文件校验失败"); }
}

function endpoint():string {
  if(process.env.MVP_DIRECTOR_ENABLED!=="1") throw new Error("导演台未就绪：尚未启用");
  const raw=process.env.MVP_DIRECTOR_COMFYUI_BASE_URL;
  if(!raw) throw new Error("导演台未就绪：尚未配置生成服务");
  try {
    const url=new URL(raw);
    const loopback=["127.0.0.1","localhost","[::1]"].includes(url.hostname);
    if(url.username || url.password || url.search || url.hash || url.pathname!=="/" ||
       !(loopback && ["http:","https:"].includes(url.protocol) || url.protocol==="https:" && url.hostname.endsWith(".ts.net"))) throw new Error();
    return url.origin;
  } catch { throw new Error("导演台未就绪：生成服务配置不正确"); }
}

// A bounded, short-lived observation; never infer runtime readiness from file presence.
export async function refreshDirectorRuntime() {
  let url:string;
  try { url=endpoint(); } catch { return; }
  if(probe?.endpoint===url && probe.expires>Date.now()) return;
  if(pending?.endpoint===url) return pending.request;
  const request=(async()=>{
    let info:NodeInfo|null=null;
    try {
      const response=await fetch(`${url}/object_info`,{cache:"no-store",signal:AbortSignal.timeout(3000),redirect:"error"});
      if(!response.ok) throw new Error();
      const data=await response.json();
      if(!data || typeof data!=="object" || Array.isArray(data)) throw new Error();
      info=data;
    } catch { /* Runtime remains unavailable; old native jobs are unaffected. */ }
    probe={endpoint:url,expires:Date.now()+5000,info};
  })();
  pending={endpoint:url,request};
  try { await request; } finally { if(pending?.request===request) pending=undefined; }
}

export function directorOption(directory:string,mode:VideoMode) {
  const data=installed(directory,mode);
  const {registry,cap,graph}=data,url=endpoint();
  const info=probe?.endpoint===url && probe.expires>Date.now()?probe.info:null;
  if(!info) throw new Error("导演台未就绪：生成服务尚未通过探测");
  const required=[...registry.engines.director.runtime.requiredCustomNodes,...registry.engines.director.runtime.requiredBuiltinNodes];
  if(required.some(name=>!info[name])) throw new Error("导演台未就绪：生成服务缺少所需节点");
  const director=info.MiniMaxH3Director.input;
  if(!director?.optional?.i2v_groups || !director.optional.r2v_groups) throw new Error("导演台未就绪：节点版本不兼容");
  const referencePorts=info.MiniMaxH3DirectorGroupReferenceToVideo.input?.optional;
  const keyframePorts=info.MiniMaxH3DirectorGroupImageToVideo.input?.optional;
  if(["ref_images","ref_videos","ref_video_audios","ref_audios"].some(name=>!referencePorts?.[name]) ||
     ["first_frame","last_frame"].some(name=>!keyframePorts?.[name])) throw new Error("导演台未就绪：素材接口版本不兼容");
  for(const node of Object.values(graph) as {class_type:string;inputs:Record<string,unknown>}[]) {
    for(const key of ["unet_name","clip_name","vae_name"]) {
      if(key in node.inputs) {
        const choices=info[node.class_type]?.input?.required?.[key]?.[0];
        if(!Array.isArray(choices) || !choices.includes(node.inputs[key])) throw new Error("导演台未就绪：所需模型不可用");
      }
    }
  }
  return { registry,cap,defaults:registry.defaults,limits:{
    minDurationSeconds:registry.parameters.durationSeconds.min,maxDurationSeconds:registry.parameters.durationSeconds.max,
    steps:registry.parameters.steps,ratios:registry.parameters.ratios,resolutions:registry.parameters.resolutions,
  }};
}

export function directorMetadata(directory:string,mode:VideoMode) {
  const {cap}=directorOption(directory,mode);
  return {workflowRevision:cap.revision,workflowOutputNodeIds:[...cap.outputNodeIds]};
}
