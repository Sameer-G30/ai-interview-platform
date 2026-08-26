import path from "path" // node's path module, used to resolve the "@/*" alias to an absolute directory
import tailwindcss from "@tailwindcss/vite" // Tailwind v4's first-party Vite plugin (no separate postcss config needed)
import react from "@vitejs/plugin-react" // enables JSX/Fast Refresh for .tsx files
import { defineConfig } from "vite" // typed config helper from Vite itself

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
    proxy: {
      // Same-origin /auth and /health so the browser never cross-origin fetches (CORS / WSL localhost traps).
      "/auth": {
        target: process.env.AIIP_API_PROXY ?? "http://127.0.0.1:8001", // this machine's uvicorn --port 8001
        changeOrigin: true, // set Host to the API so FastAPI sees a normal request
      },
      "/health": {
        target: process.env.AIIP_API_PROXY ?? "http://127.0.0.1:8001", // same target as /auth
        changeOrigin: true, // set Host to the API so FastAPI sees a normal request
      },
      "/jobs": {
        target: process.env.AIIP_API_PROXY ?? "http://127.0.0.1:8001", // same target as /auth
        changeOrigin: true, // set Host to the API so FastAPI sees a normal request
      },
      "/resumes": {
        target: process.env.AIIP_API_PROXY ?? "http://127.0.0.1:8001", // same target as /auth so POST /resumes stays same-origin
        changeOrigin: true, // set Host to the API so FastAPI sees a normal request
      },
      "/postings": {
        target: process.env.AIIP_API_PROXY ?? "http://127.0.0.1:8001", // same target as /auth so /postings stays same-origin
        changeOrigin: true, // set Host to the API so FastAPI sees a normal request
      },
      "/matches": {
        target: process.env.AIIP_API_PROXY ?? "http://127.0.0.1:8001", // same target as /auth so /matches stays same-origin
        changeOrigin: true, // set Host to the API so FastAPI sees a normal request
      },
      "/interviews": {
        target: process.env.AIIP_API_PROXY ?? "http://127.0.0.1:8001", // same target as /auth so /interviews stays same-origin
        changeOrigin: true, // set Host to the API so FastAPI sees a normal request
      },
    },
  },
})
