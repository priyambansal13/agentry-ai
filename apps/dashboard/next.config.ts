import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

// One .env at the repo root serves every app and the Python backend.
try {
  process.loadEnvFile("../../.env");
} catch {
  // In production, env vars come from the platform.
}

const nextConfig: NextConfig = {
  transpilePackages: ["@agentry/ui"],
  // Self-contained server bundle for the Docker image (traces files from the monorepo root).
  output: "standalone",
  outputFileTracingRoot: fileURLToPath(new URL("../../", import.meta.url)),
  // files are uploaded through server actions (API limits: 10 MB a knowledge file, 20 MB a CA file, 100 MB an upload-hub batch)
  experimental: { serverActions: { bodySizeLimit: "101mb" } },
};

export default nextConfig;
