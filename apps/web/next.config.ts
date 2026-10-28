import type { NextConfig } from "next";
import { resolve } from "node:path";
const config: NextConfig = {
  poweredByHeader: false, transpilePackages: ["@hub/shared"],
  outputFileTracingRoot: resolve(process.cwd(), "../.."),
  outputFileTracingIncludes: { "/api/mvp/**": ["../../workflows/*_api.json", "../../workflows/*_mapping.json", "../../workflows/h3_capabilities*.json", "../../workflows/validation/director-v1.0.0.json", "../worker/src/comfy_hub_worker/mapping.py", "../worker/src/comfy_hub_worker/director_workflow.py", "../worker/src/comfy_hub_worker/director_contract.py"] },
  outputFileTracingExcludes: { "/*": ["./.local-data/**/*", "./.env*", "../../.runtime/**/*", "../../.venv/**/*"] },
};
export default config;
