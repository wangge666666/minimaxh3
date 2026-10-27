import { expect, test } from "vitest";
import { GET } from "./route";
test("健康检查只报告网站进程，不冒充依赖服务在线", async () => {
  const response = GET();
  expect(response.status).toBe(200);
  expect(response.headers.get("cache-control")).toBe("no-store");
  expect(await response.json()).toEqual({ service: "comfyui-cloud-hub", status: "ok", stage: "private-studio" });
});
