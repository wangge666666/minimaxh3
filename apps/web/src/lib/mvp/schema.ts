import { z } from "zod";
import { workflowEngineSchema } from "@hub/shared";
import { validVideoFrames, framesForDuration, minDurationSeconds, maxDurationSeconds, stepOptions, videoSizes, type Asset } from "./h3";
export const modes = ["text", "img2img", "h3_t2v", "h3_i2v", "h3_r2v"] as const;
export type Mode = typeof modes[number];
export function isVideoMode(mode: string) { return mode.startsWith("h3_"); }
export function needsReference(mode: string) { return ["img2img", "h3_i2v", "h3_r2v"].includes(mode); }
export const createSchema = z.object({
  requestId: z.uuid(), mode: z.enum(modes),
  workflowEngine: workflowEngineSchema.optional(),
  prompt: z.string().trim().min(1, "请输入提示词").max(2000, "提示词最多 2000 字"),
  width: z.number().int(), height: z.number().int(),
  seed: z.number().int().min(0).max(4294967295), denoise: z.number().min(0.1).max(1),
  frames: z.number().int().refine(validVideoFrames,"视频帧数必须在 107–362 之间并符合 17k+5 规则").optional(), fps: z.literal(24).optional(),
  durationSeconds:z.number().min(minDurationSeconds).max(maxDurationSeconds).optional(),
  steps: z.union(stepOptions.map(v => z.literal(v))).optional(),
  sound: z.boolean().optional(), referenceVideoAudio: z.boolean().optional(),
  refImageSize: z.enum(["match", "max"]).optional(),
}).strict().superRefine((p, ctx) => {
  if (isVideoMode(p.mode)) {
    if (!(p.width===640 && p.height===384) && !videoSizes.some(([w,h]) => p.width===w && p.height===h)) ctx.addIssue({code:"custom",path:["width"],message:"请选择支持的视频比例与分辨率"});
    if(p.durationSeconds!==undefined && p.frames!==framesForDuration(p.durationSeconds)) ctx.addIssue({code:"custom",path:["frames"],message:"帧数与所选时长不一致"});
  } else if (![256,512,768].includes(p.width) || ![256,512,768].includes(p.height)) {
    ctx.addIssue({code:"custom",path:["width"],message:"图片尺寸只能使用 256、512 或 768"});
  }
  if (!isVideoMode(p.mode) && p.workflowEngine === "director") ctx.addIssue({code:"custom",path:["workflowEngine"],message:"导演台仅支持视频创作"});
});
export type CreateJob = z.infer<typeof createSchema>;
// Server-owned metadata is deliberately absent from the browser request schema.
export const storedParamsSchema = createSchema.safeExtend({
  workflowRevision: z.union([z.string().regex(/^native-sha256:[a-f0-9]{64}$/),z.literal("director-v1.0.0")]).optional(),
  workflowOutputNodeIds: z.array(z.string().regex(/^[a-zA-Z0-9_:-]{1,128}$/)).min(1).max(16).optional(),
}).superRefine((p,ctx)=>{
  if(p.workflowEngine==="director" && (p.workflowRevision!=="director-v1.0.0" || JSON.stringify(p.workflowOutputNodeIds)!=='["8"]')) ctx.addIssue({code:"custom",path:["workflowRevision"],message:"导演台任务缺少固定版本或输出"});
  if(p.workflowEngine!=="director" && p.workflowRevision?.startsWith("director-")) ctx.addIssue({code:"custom",path:["workflowRevision"],message:"工作流引擎与修订不一致"});
});
export type StoredParams = z.infer<typeof storedParamsSchema>;
export type Job = StoredParams & { id: string; status: string; created_at: number; updated_at: number; message: string; prompt_id: string | null; queue_position: number | null; media_type: "image"|"video"; assets: Asset[]; has_poster:boolean };
