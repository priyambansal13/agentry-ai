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
  // knowledge files and invoice spreadsheets are uploaded through server actions (API limit: 10 MB)
  experimental: { serverActions: { bodySizeLimit: "11mb" } },
};

export default nextConfig;
