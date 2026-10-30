import type { NextConfig } from "next";

// 画面からの /api/... は FastAPI に転送する(同じオリジンに見えるので CORS の設定がいらない)
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  experimental: {
    // rewrites の中継の待ち時間の上限(既定は30秒)。J-Quants から初めて日足を取るときは、
    // 回数の上限で少し待つことがあるので、余裕をもたせる(API 側は長く待つ前に目安を返す:backend/main.py)
    proxyTimeout: 120_000,
  },
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
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
};

export default nextConfig;
