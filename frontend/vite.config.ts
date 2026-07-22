import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

/**
 * 前端构建：产物输出到 dist，由 FastAPI / Nginx 同源托管。
 * base=/zq/：单域名子路径部署；开发时把 /zq/api 代理到本机 uvicorn。
 */
export default defineConfig({
  base: "/zq/",
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/zq/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
