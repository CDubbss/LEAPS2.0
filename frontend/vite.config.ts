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
          target: "http://localhost:8001",
          changeOrigin: true,
          headers: proxyHeaders,
        },
      },
    },
  };
});
