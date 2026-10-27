import { expect, test } from "vitest";
import { jobStatusSchema, terminalStatuses } from "./index";
test("协议拒绝未知状态", () => { expect(jobStatusSchema.safeParse("success").success).toBe(false); });
test("终态包含完成、失败和取消", () => { expect(terminalStatuses).toEqual(["completed", "failed", "canceled"]); });
