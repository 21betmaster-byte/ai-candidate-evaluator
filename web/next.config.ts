import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  experimental: {
    // Server actions are used for Poll Now + Settings save.
    serverActions: { bodySizeLimit: "1mb" },
  },
};

export default nextConfig;
