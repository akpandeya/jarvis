import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

// Output goes into jarvis/web/static so FastAPI can serve it directly.
// Dev proxies /api → 127.0.0.1:8745 (the jarvis web default port).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8745",
        changeOrigin: false,
        ws: false,
      },
    },
  },
  build: {
    outDir: path.resolve(__dirname, "../jarvis/web/static"),
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
  },
});
