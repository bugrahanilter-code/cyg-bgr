import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The dev server proxies /api to the backend so the browser never needs to
// know about ports, and no CORS configuration is required during development.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    // "true" listens on every interface INCLUDING IPv6. "0.0.0.0" is IPv4 only,
    // and on Windows "localhost" usually resolves to ::1 first, so a browser
    // would try [::1]:3000, find nothing listening, and show a blank page while
    // curl still worked by falling back to IPv4.
    host: true,
    port: 3000,
    strictPort: true,
    proxy: {
      "/api": {
        // Explicit IPv4: the backend listens on 127.0.0.1 only, and "localhost"
        // can resolve to ::1 first, which would make the proxy fail.
        target: process.env.VITE_BACKEND_URL || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
