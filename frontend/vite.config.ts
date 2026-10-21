import path from "path" // node's path module, used to resolve the "@/*" alias to an absolute directory
import tailwindcss from "@tailwindcss/vite" // Tailwind v4's first-party Vite plugin (no separate postcss config needed)
import react from "@vitejs/plugin-react" // enables JSX/Fast Refresh for .tsx files
import { defineConfig } from "vitest/config" // Vite config plus the single Vitest runner (no second test tool)

// Every backend route prefix the SPA calls same-origin (no CORS, no WSL localhost traps).
const API_PREFIXES = [
  "/auth", "/health", "/jobs", "/resumes", "/postings", "/matches",
  "/interviews", "/scores", "/reports", "/admin",
] // 10 prefixes; the plan's "11" counted /admin twice in prose
const baseProxy = {
  target: process.env.AIIP_API_PROXY ?? "http://127.0.0.1:8001", // this machine's uvicorn --port 8001
  changeOrigin: true, // set Host to the API so FastAPI sees a normal request
}
const adminProxy = {
  ...baseProxy,
  bypass(req: { headers: { accept?: string } }) {
    // Browser document navigations to the SPA route /admin must not be stolen by the API proxy.
    // apiFetch sets Accept: application/json, so GET /admin/users still reaches FastAPI.
    if (req.headers.accept?.includes("text/html")) return "/index.html" // Vite serves the SPA
  },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()], // react() handles JSX; tailwindcss() compiles Tailwind classes at build/dev time
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"), // lets imports use "@/components/..." instead of "../../.."
    },
  },
  // This machine already has another Vite app on 5173. Stay on 5174 and refuse to hop to 5175.
  server: {
    host: "localhost", // printed URL matches FRONTEND_ORIGIN=http://localhost:5174
    port: 5174, // this project's Vite port (Secure Chat uses 5173)
    strictPort: true, // fail instead of silently opening 5175 when 5174 is busy
    proxy: Object.fromEntries(
      // One entry per API prefix; /admin additionally needs the HTML bypass below.
      API_PREFIXES.map((prefix) => [prefix, prefix === "/admin" ? adminProxy : baseProxy]),
    ),
  },
  // Node-level smoke tests. They render the real route tree in jsdom; they do not open a browser.
  test: {
    environment: "jsdom", // DOM for React Testing Library without Playwright
    setupFiles: ["./src/smoke/setup.ts"], // matchMedia stub + testing-library cleanup
    include: ["src/smoke/**/*.test.tsx"], // one suite; do not add a second runner
    css: false, // class names are enough; do not compile Tailwind during smoke tests
  },
})
