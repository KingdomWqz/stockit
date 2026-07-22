import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/svc/api/:path*",
        destination: "http://127.0.0.1:8000/svc/api/:path*",
      },
    ];
  },
};

export default nextConfig;
