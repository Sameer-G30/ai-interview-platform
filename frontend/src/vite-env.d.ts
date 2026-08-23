/// <reference types="vite/client" /> // pulls in Vite's ImportMeta and asset-module types for this app

// Describes the Vite-injected env vars this frontend is allowed to read at build time.
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string // optional override for the FastAPI origin; defaults to http://localhost:8000
}

// Extends Vite's ImportMeta so `import.meta.env.VITE_API_BASE_URL` is typed, not `any`.
interface ImportMeta {
  readonly env: ImportMetaEnv // the bag of VITE_* variables plus Vite's built-in DEV/PROD/MODE flags
}
