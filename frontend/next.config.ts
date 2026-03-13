import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: process.env.NEXT_EXPORT === "1" ? "export" : undefined,
};

export default nextConfig;
