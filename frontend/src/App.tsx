// Button is shadcn/ui's first installed primitive; rendering it here proves Tailwind + shadcn
// are wired correctly end-to-end. Real pages/layout are built in the frontend-shell phase.
import { Button } from "@/components/ui/button"

function App() {
  return (
    // Tailwind utility classes center the placeholder both horizontally and vertically.
    <div className="flex min-h-svh flex-col items-center justify-center gap-4">
      <h1 className="text-2xl font-semibold">AI Interview Intelligence Platform</h1>
      <p className="text-muted-foreground">Scaffolding complete — real screens land in later phases.</p>
      {/* Renders a shadcn Button; if this looks styled, Tailwind + shadcn are both working. */}
      <Button>Toolchain OK</Button>
    </div>
  )
}

export default App
