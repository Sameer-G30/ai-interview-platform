import { Link } from "react-router-dom" // send the user back to the role landing / login

import { Button } from "@/components/ui/button" // styled link button
import { useAuth } from "@/hooks/use-auth" // pick a sensible "go home" target
import { homePathForUser } from "@/lib/home-path" // /candidate or /recruiter when signed in

// Catch-all 404 for unknown paths.
export function NotFoundPage() {
  const { user } = useAuth() // may be null on a public 404
  const href = user ? homePathForUser(user) : "/login" // signed-in users go home; guests go to login

  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-4 p-6">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="text-muted-foreground">That URL is not part of this app.</p>
      <Button asChild>
        <Link to={href}>Go back</Link>
      </Button>
    </div>
  )
}
