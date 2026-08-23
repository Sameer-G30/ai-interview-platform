import { Loader2Icon } from "lucide-react" // spinning icon used as a full-page wait state

// Centered spinner shown while we restore a session from localStorage or wait on /auth/me.
export function PageSpinner() {
  return (
    <div className="flex min-h-svh items-center justify-center bg-background">
      <Loader2Icon aria-label="Loading" className="size-8 animate-spin text-muted-foreground" />
    </div>
  )
}
