import { StrictMode } from "react" // double-invokes effects in dev to catch unsafe side effects
import { createRoot } from "react-dom/client" // React 19 root API
import "./index.css" // Tailwind v4 + shadcn theme tokens
import App from "./App.tsx" // providers + router

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
