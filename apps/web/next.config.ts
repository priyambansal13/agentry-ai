import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

try {
  process.loadEnvFile("../../.env");
} catch {
  // In production, env vars come from the platform.
}

const nextConfig: NextConfig = {
  transpilePackages: ["@agentry/ui"],
  // development only: let a Cloudflare quick tunnel serve the site (demo links for prospects before deployment)
  allowedDevOrigins: ["*.trycloudflare.com"],
  // Self-contained server bundle for the Docker image (traces files from the monorepo root).
  output: "standalone",
  outputFileTracingRoot: fileURLToPath(new URL("../../", import.meta.url)),
};

export default nextConfig;
