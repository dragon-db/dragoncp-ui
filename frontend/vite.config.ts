import { hostname } from "node:os"
import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { TanStackRouterVite } from "@tanstack/router-vite-plugin"
import { defineConfig } from "vite"

// Named backends for the dev proxy. Pick one with DRAGONCP_BACKEND=dev|prod
// (see the dev / dev:prod npm scripts), or point somewhere else entirely with
// DRAGONCP_BACKEND_URL, which always wins.
//   dev  - local `python app.py` from this checkout (PORT=5050)
//   prod - the live dragoncp-ui.service gunicorn, real data and real transfers
const BACKENDS = {
  dev: "http://localhost:5050",
  prod: "http://localhost:5000",
} as const

const backendName = (process.env.DRAGONCP_BACKEND ?? "dev") as keyof typeof BACKENDS
const backendUrl =
  process.env.DRAGONCP_BACKEND_URL ?? BACKENDS[backendName] ?? BACKENDS.dev

console.log(
  `\n  [35m➤[0m  DragonCP proxy target: [1m${backendUrl}[0m` +
    (backendUrl === BACKENDS.prod
      ? "  [33m(LIVE PRODUCTION — writes hit real data)[0m\n"
      : "  [2m(local dev backend)[0m\n"),
)

// Allow opening the server via Tailscale MagicDNS hostnames: the machine's
// short name (e.g. "dragondb") and full .ts.net names.
const allowedHosts = [hostname().toLowerCase(), ".ts.net"]

const proxy = {
  "/api": {
    target: backendUrl,
    changeOrigin: true,
  },
  "/socket.io": {
    target: backendUrl,
    changeOrigin: true,
    ws: true,
  },
}

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
    allowedHosts,
    proxy,
  },
  // `vite preview` serves the built files, so it carries no dev client and
  // never reloads the page by itself. That matters on a phone: backgrounding
  // the tab drops the dev server's websocket, and the dev client answers that
  // by reloading the whole page the moment you switch back. Preview does not
  // inherit the server proxy, hence the repeat above.
  preview: {
    port: 5181,
    allowedHosts,
    proxy,
  },
})
