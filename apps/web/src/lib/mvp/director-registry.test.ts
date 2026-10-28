import { afterEach, expect, test, vi } from "vitest";
import { cpSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { randomUUID } from "node:crypto";
import { pinWorkflow, workflowOptions, refreshDirectorRuntime } from "./workflows";
import { JobStore } from "./store";

const directories:string[]=[];
let port=19000;
afterEach(()=>{vi.unstubAllEnvs();vi.unstubAllGlobals();directories.splice(0).forEach(path=>rmSync(path,{recursive:true,force:true}));});
function fixture() {
  const path=mkdtempSync(join(tmpdir(),"hub-director-"));directories.push(path);
  cpSync(resolve("../../workflows"),path,{recursive:true});
  vi.stubEnv("MVP_DIRECTOR_ENABLED","1");
  vi.stubEnv("MVP_DIRECTOR_COMFYUI_BASE_URL",`http://127.0.0.1:${++port}`);
  vi.stubEnv("MVP_WORKFLOW_DIRECTORY",path);
  const info:Record<string,any>={};
  const registry=JSON.parse(readFileSync(join(path,"h3_capabilities.json"),"utf8"));
  for(const name of [...registry.engines.director.runtime.requiredCustomNodes,...registry.engines.director.runtime.requiredBuiltinNodes]) info[name]={input:{required:{},optional:{}}};
  info.MiniMaxH3Director.input.optional={i2v_groups:["MMX_DIR_GROUP"],r2v_groups:["MMX_DIR_GROUP"]};
  info.MiniMaxH3DirectorGroupReferenceToVideo.input.optional={ref_images:["COMFY_AUTOGROW_V3"],ref_videos:["COMFY_AUTOGROW_V3"],ref_video_audios:["COMFY_AUTOGROW_V3"],ref_audios:["COMFY_AUTOGROW_V3"]};
  info.MiniMaxH3DirectorGroupImageToVideo.input.optional={first_frame:["IMAGE"],last_frame:["IMAGE"]};
  info.UNETLoader.input.required.unet_name=[["minimax_h3_fl2va_pruned_int8_convrot.safetensors","minimax_h3_ref2va_pruned_int8_convrot.safetensors"]];
  info.CLIPLoader.input.required.clip_name=[["qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"]];
  info.VAELoader.input.required.vae_name=[["minimax_h3_video_vae_fp16.safetensors","minimax_h3_audio_vae_fp32.safetensors"]];
  const fetcher=vi.fn(async()=>Response.json(info));vi.stubGlobal("fetch",fetcher);
  return {path,info,fetcher};
}
const params=()=>({requestId:randomUUID(),mode:"h3_t2v" as const,workflowEngine:"director" as const,prompt:"a boat",width:640,height:360,seed:42,denoise:1});

test("accepted files alone are insufficient; explicit enable plus real node/model observation are required",async()=>{
  const {path,fetcher}=fixture();
  expect(workflowOptions(path).filter(o=>o.engine==="director").every(o=>!o.ready)).toBe(true);
  await refreshDirectorRuntime();
  expect(fetcher).toHaveBeenCalledOnce();
  expect(workflowOptions(path).filter(o=>o.engine==="director").every(o=>o.ready && o.defaults.steps===20)).toBe(true);
  expect(pinWorkflow(params(),path)).toMatchObject({workflowEngine:"director",workflowRevision:"director-v1.0.0",workflowOutputNodeIds:["8"]});
  vi.stubEnv("MVP_DIRECTOR_ENABLED","0");
  expect(()=>pinWorkflow(params(),path)).toThrow("未就绪");
});
test("missing nodes/models and unreachable runtime keep native available",async()=>{
  const {path,info,fetcher}=fixture();delete info.LoadAudio;
  await refreshDirectorRuntime();
  expect(workflowOptions(path).filter(o=>o.engine==="director").every(o=>!o.ready)).toBe(true);
  expect(workflowOptions(path).filter(o=>o.engine==="native").every(o=>o.ready)).toBe(true);
  vi.stubEnv("MVP_DIRECTOR_COMFYUI_BASE_URL",`http://127.0.0.1:${++port}`);
  info.LoadAudio={};info.UNETLoader.input.required.unet_name=[[]];await refreshDirectorRuntime();
  expect(()=>pinWorkflow(params(),path)).toThrow("模型不可用");
  vi.stubEnv("MVP_DIRECTOR_COMFYUI_BASE_URL",`http://127.0.0.1:${++port}`);
  fetcher.mockRejectedValueOnce(new Error("offline"));await refreshDirectorRuntime();
  expect(()=>pinWorkflow(params(),path)).toThrow("尚未通过探测");
});
test("changed template/evidence and mismatched builder cannot be treated as the fixed revision",async()=>{
  const {path}=fixture();await refreshDirectorRuntime();
  const file=join(path,"h3_director_t2v_api.json"),original=readFileSync(file,"utf8");
  writeFileSync(file,original+"\n");expect(()=>pinWorkflow(params(),path)).toThrow("校验失败");writeFileSync(file,original);
  const evidence=join(path,"validation/director-v1.0.0.json"),originalEvidence=readFileSync(evidence,"utf8");writeFileSync(evidence,JSON.stringify({schemaVersion:1,revision:"director-v1.0.0",releaseAcceptanceCases:[]}));
  expect(()=>pinWorkflow(params(),path)).toThrow("校验失败");
  writeFileSync(evidence,originalEvidence);vi.stubEnv("MVP_DIRECTOR_BUILDER_DIRECTORY",path);
  expect(()=>pinWorkflow(params(),path)).toThrow("校验失败");
});
test("Director job metadata is pinned and request retries survive disablement and removed files",async()=>{
  const {path}=fixture();await refreshDirectorRuntime();const db=new JobStore(":memory:");
  try {
    const p=params(),first=db.create(p,null);expect(first.workflowRevision).toBe("director-v1.0.0");
    vi.stubEnv("MVP_DIRECTOR_ENABLED","0");rmSync(join(path,"h3_director_t2v_api.json"));
    expect(db.create(p,null).id).toBe(first.id);
    expect(db.claim(randomUUID())?.workflowOutputNodeIds).toEqual(["8"]);
    expect(()=>db.create(params(),null)).toThrow("未就绪");
  } finally {db.db.close();}
});
test("invalid runtime destinations do not make network requests",async()=>{
  const {fetcher}=fixture();
  for(const url of ["https://example.com","http://192.168.1.1","http://127.0.0.1/a","http://user:password@127.0.0.1"]){
    vi.stubEnv("MVP_DIRECTOR_COMFYUI_BASE_URL",url);await refreshDirectorRuntime();
  }
  expect(fetcher).not.toHaveBeenCalled();
});
