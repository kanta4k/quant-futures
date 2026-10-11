import type { NextConfig } from "next";

// 브라우저는 Next.js(/api/*)만 호출하고, Next.js가 로컬 FastAPI로 프록시한다.
// 거래소 키는 백엔드(OS 키체인)에만 존재한다 (PRD 4.3).
const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` }];
  },
};

export default nextConfig;
