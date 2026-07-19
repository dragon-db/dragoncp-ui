import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { TanStackRouterVite } from "@tanstack/router-vite-plugin"
import { defineConfig } from "vite"

// Backend origin for the dev proxy; override when :5000 is taken
// (e.g. DRAGONCP_BACKEND_URL=http://localhost:5050 npx vite)
const backendUrl = process.env.DRAGONCP_BACKEND_URL ?? "http://localhost:5000"

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    TanStackRouterVite(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    // Allow opening the dev server via Tailscale MagicDNS hostnames
    allowedHosts: [".ts.net"],
    proxy: {
      "/api": {
        target: backendUrl,
        changeOrigin: true,
      },
      "/socket.io": {
        target: backendUrl,
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
