import { z } from "zod";
export const workflowEngineSchema = z.enum(["native", "director"]);
export type WorkflowEngine = z.infer<typeof workflowEngineSchema>;
export const jobStatusSchema = z.enum(["queued", "claimed", "running", "uploading", "completed", "failed", "canceled"]);
export type JobStatus = z.infer<typeof jobStatusSchema>;
export const terminalStatuses: readonly JobStatus[] = ["completed", "failed", "canceled"];
export const apiErrorSchema = z.object({ error: z.object({ code: z.string(), message: z.string(), requestId: z.string().optional() }) });
