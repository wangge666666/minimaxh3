import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { storedParamsSchema, type CreateJob, type StoredParams } from "./schema";
import { nativeDefaults, nativeLimits, videoModes, type WorkflowOption } from "./workflow-options";
import { directorMetadata, directorOption } from "./director-registry";
export { refreshDirectorRuntime } from "./director-registry";

export class WorkflowUnavailable extends Error {}
export function workflowDirectory() {
  return resolve(/* turbopackIgnore: true */ process.env.MVP_WORKFLOW_DIRECTORY || resolve(process.cwd(), "../../workflows"));
}
function nativeMetadata(mode: string, directory: string) {
  if (!["text", "img2img", ...videoModes].includes(mode)) throw new WorkflowUnavailable("不支持的工作流");
  const stem = mode.startsWith("h3_") ? mode : `z_image_turbo_${mode}`;
  const hash = createHash("sha256");
  const files = [`${stem}_api.json`, `${stem}_mapping.json`];
  let mapping: { version?: string; template?: string; outputs?: unknown } = {};
  let template: Record<string, { class_type?: string }> = {};
  try {
    for (const name of files) {
      // Canonical LF permits the same revision on Windows and Unix checkouts.
      const source = readFileSync(resolve(directory, name), "utf8").replace(/\r\n/g, "\n");
      hash.update(name + "\0" + source + "\0");
      if (name.endsWith("_mapping.json")) mapping = JSON.parse(source);
      else template = JSON.parse(source);
    }
    if (mapping.version !== "1" || mapping.template !== files[0] || !Array.isArray(mapping.outputs) || !mapping.outputs.length ||
      !mapping.outputs.every((id: unknown) => typeof id === "string" && template[id]?.class_type === (mode.startsWith("h3_") ? "SaveVideo" : "SaveImage"))) throw new Error();
    return { workflowRevision: `native-sha256:${hash.digest("hex")}`, workflowOutputNodeIds: mapping.outputs as string[] };
  } catch { throw new WorkflowUnavailable("原生工作流文件缺失或不可用，请检查安装"); }
}

export function workflowOptions(directory = workflowDirectory()): WorkflowOption[] {
  return videoModes.flatMap(mode => {
    let nativeReason: string | undefined;
    try { nativeMetadata(mode, directory); } catch { nativeReason = "原生工作流安装不完整"; }
    let director:WorkflowOption;
    try {
      const {defaults,limits}=directorOption(directory,mode);
      director={engine:"director",mode,ready:true,defaults,limits};
    } catch(error) {
      director={engine:"director",mode,ready:false,reason:(error as Error).message,defaults:nativeDefaults,limits:nativeLimits};
    }
    return [
      { engine: "native" as const, mode, ready: !nativeReason, reason: nativeReason, defaults: nativeDefaults, limits: nativeLimits },
      director,
    ];
  });
}

export function pinWorkflow(params: CreateJob, directory = workflowDirectory()): StoredParams {
  const engine = params.workflowEngine === undefined ? "native" : params.workflowEngine;
  let metadata: {workflowRevision:string;workflowOutputNodeIds:string[]};
  if(engine==="director") {
    if(!videoModes.includes(params.mode as typeof videoModes[number])) throw new WorkflowUnavailable("导演台仅支持视频创作");
    try {
      const mode=params.mode as typeof videoModes[number],{registry}=directorOption(directory,mode),p=registry.parameters;
      if(!p.dimensions.some(([w,h])=>w===params.width && h===params.height) || !p.steps.includes(params.steps??20) || !p.frames.includes(params.frames??124) || !p.refImageSize.includes(params.refImageSize??"match") || params.seed<p.seed.min || params.seed>p.seed.max || (params.durationSeconds!==undefined && (params.durationSeconds<p.durationSeconds.min || params.durationSeconds>p.durationSeconds.max))) throw new Error("参数超出导演台能力范围");
      metadata=directorMetadata(directory,mode);
    } catch(error) { throw new WorkflowUnavailable(`导演台未就绪：${(error as Error).message}`); }
  } else {
    metadata=nativeMetadata(params.mode,directory);
  }
  const defaults = params.mode.startsWith("h3_") ? {
    frames: params.frames ?? 124, fps: 24 as const, steps: params.steps ?? 20,
    sound: params.sound ?? true, referenceVideoAudio: params.referenceVideoAudio ?? true,
    refImageSize: params.refImageSize ?? "match",
  } : {};
  return storedParamsSchema.parse({ ...params, ...defaults, workflowEngine: engine, ...metadata });
}
