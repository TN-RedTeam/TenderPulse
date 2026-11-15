import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// En développement, les appels /api sont relayés vers le backend FastAPI.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
