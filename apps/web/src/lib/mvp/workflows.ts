import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { storedParamsSchema, type CreateJob, type StoredParams } from "./schema";
import { nativeDefaults, nativeLimits, videoModes, type WorkflowOption } from "./workflow-options";

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

// No registry format has been delivered. Do not interpret a guessed schema or
// treat file presence as GPU acceptance. This is the single adapter to replace
// once the workflow owner supplies the reviewed registry and loader commit.
export function workflowOptions(directory = workflowDirectory()): WorkflowOption[] {
  const reason = existsSync(resolve(directory, "h3_capabilities.json"))
    ? "导演台尚未完成接口对接与验收"
    : "导演台尚未就绪，正在等待工作流交付与验收";
  return videoModes.flatMap(mode => {
    let nativeReason: string | undefined;
    try { nativeMetadata(mode, directory); } catch { nativeReason = "原生工作流安装不完整"; }
    return [
      { engine: "native" as const, mode, ready: !nativeReason, reason: nativeReason, defaults: nativeDefaults, limits: nativeLimits },
      { engine: "director" as const, mode, ready: false, reason, defaults: nativeDefaults, limits: nativeLimits },
    ];
  });
}

export function pinWorkflow(params: CreateJob, directory = workflowDirectory()): StoredParams {
  const engine = params.workflowEngine === undefined ? "native" : params.workflowEngine;
  if (engine !== "native") throw new WorkflowUnavailable("导演台尚未就绪，请选择原生生成方式");
  const defaults = params.mode.startsWith("h3_") ? {
    frames: params.frames ?? 124, fps: 24 as const, steps: params.steps ?? 20,
    sound: params.sound ?? true, referenceVideoAudio: params.referenceVideoAudio ?? true,
    refImageSize: params.refImageSize ?? "match",
  } : {};
  return storedParamsSchema.parse({ ...params, ...defaults, workflowEngine: engine, ...nativeMetadata(params.mode, directory) });
}
