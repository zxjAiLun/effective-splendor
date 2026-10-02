import type { NextConfig } from "next";

// Public deployment under a subpath (e.g. https://pearllover.site/splendor)
// builds with VITE_STUDIO_BASE_PATH set; unset keeps the historical
// root-relative behavior for local development and tests.
const basePath = process.env.VITE_STUDIO_BASE_PATH?.trim();

const nextConfig: NextConfig = {
  ...(basePath ? { basePath } : {}),
};

export default nextConfig;
