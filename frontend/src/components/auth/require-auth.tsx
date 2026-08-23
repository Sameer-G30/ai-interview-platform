import { Navigate, Outlet, useLocation } from "react-router-dom" // redirect helpers + nested route slot

import { PageSpinner } from "@/components/layout/page-spinner" // full-page wait while /auth/me restores the session
import { Button } from "@/components/ui/button" // used on the "session failed" fallback
import { useAuth } from "@/hooks/use-auth" // current user, loading flags, logout

// Layout guard for every authenticated route: waits for /auth/me, then either redirects to login or renders children.
export function RequireAuth() {
  const { user, tokens, isLoading, isError, logout } = useAuth() // session state from AuthProvider
  const location = useLocation() // remembered so login can send the user back here after signing in

  if (isLoading) {
    return <PageSpinner /> // restoring a session from localStorage; do not flash the login page
  }

  if (isError) {
    return (
      <div className="flex min-h-svh flex-col items-center justify-center gap-4 p-6">
        <p className="text-muted-foreground">Could not restore your session. Sign in again.</p>
        <Button
          type="button"
          onClick={() => {
            void logout() // drop the broken local pair; RequireAuth will then redirect to /login
          }}
        >
          Sign in again
        </Button>
      </div>
    )
  }

  if (!tokens || !user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} /> // no session; send them to login
  }

  return <Outlet /> // user is loaded; render the nested shell / role routes
}
