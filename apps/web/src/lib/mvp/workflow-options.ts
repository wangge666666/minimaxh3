import type { WorkflowEngine } from "@hub/shared";
import { minDurationSeconds, maxDurationSeconds, stepOptions, ratios, resolutions } from "./h3";

export const videoModes = ["h3_t2v", "h3_i2v", "h3_r2v"] as const;
export type VideoMode = typeof videoModes[number];
export type WorkflowOption = {
  engine: WorkflowEngine;
  mode: VideoMode;
  ready: boolean;
  reason?: string;
  defaults: { steps: number; durationSeconds: number };
  limits: { minDurationSeconds: number; maxDurationSeconds: number; steps: readonly number[]; ratios: readonly string[]; resolutions: readonly number[] };
};
export const nativeDefaults = { steps: 20, durationSeconds: 5 };
export const nativeLimits = { minDurationSeconds, maxDurationSeconds, steps: stepOptions, ratios, resolutions };
export function workflowOption(options: readonly WorkflowOption[] | undefined, mode: string, engine: WorkflowEngine) {
  return options?.find(option => option.mode === mode && option.engine === engine);
}
