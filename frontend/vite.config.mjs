import { defineConfig } from "vite";

// Vite config for Krishi Saarthi frontend.
// Proxies /api calls to the FastAPI backend on port 8000
// so fetch("/api/voice-audio") works in dev.

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
