import type { NextConfig } from "next";

const isStaticExport = process.env.NEXT_EXPORT === "1";

const nextConfig: NextConfig = {
  output: isStaticExport ? "export" : undefined,
  env: {
    NEXT_PUBLIC_STATIC_EXPORT: isStaticExport ? "1" : "",
  },
};

export default nextConfig;
