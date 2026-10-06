import type { NextConfig } from "next";

const API_URL = process.env.API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // the Docker image runs the standalone server; locally `npm run build && npm start` works as usual
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  agentRules: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
};

export default nextConfig;
