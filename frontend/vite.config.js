import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const backend = process.env.SENTINEL_BACKEND || "http://localhost:8000";

// `npm run dev` serves the UI on :5173 and proxies API/WebSocket traffic to the backend.
// `npm run build` writes straight into the FastAPI static folder, which serves it in production.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../app/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": backend,
      "/demo": backend,
      "/health": backend,
      "/metrics": backend,
      "/docs": backend,
      "/openapi.json": backend,
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
});
