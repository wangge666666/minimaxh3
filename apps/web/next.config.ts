import type { NextConfig } from "next";
import { resolve } from "node:path";
const config: NextConfig = {
  poweredByHeader: false, transpilePackages: ["@hub/shared"],
  outputFileTracingRoot: resolve(process.cwd(), "../.."),
  outputFileTracingIncludes: { "/api/mvp/**": ["../../workflows/*_api.json", "../../workflows/*_mapping.json"] },
  outputFileTracingExcludes: { "/*": ["./.local-data/**/*", "./.env*", "../../.runtime/**/*", "../../.venv/**/*"] },
};
export default config;
