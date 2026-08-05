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
})
