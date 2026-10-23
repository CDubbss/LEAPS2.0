import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig(({ mode }) => {
  // Load backend .env so the proxy can forward Basic Auth when REVIEW_PASSWORD is set
  const env = loadEnv(mode, path.resolve(__dirname, "../backend"), "");
  const reviewPass = env.REVIEW_PASSWORD || "";
  const proxyHeaders: Record<string, string> = reviewPass
    ? { Authorization: `Basic ${Buffer.from(`:${reviewPass}`).toString("base64")}` }
    : {};

  // `--mode preview` runs against an isolated backend instance on 8004
  // (used by tooling so the main dev stack on 8001/5173 is never disturbed)
  const apiTarget =
    mode === "preview" ? "http://localhost:8004" : "http://localhost:8001";

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: apiTarget,
          changeOrigin: true,
          headers: proxyHeaders,
        },
      },
    },
  };
});
