import { Navigate, Outlet } from "react-router-dom" // redirect signed-in users away from login/register

import { PageSpinner } from "@/components/layout/page-spinner" // wait while we decide if a stored session is valid
import { useAuth } from "@/hooks/use-auth" // current user + loading flag
import { homePathForUser } from "@/lib/home-path" // role-aware landing path after a successful session restore

// Layout guard for /login and /register: signed-in users skip the forms and go to their role home.
export function RequireGuest() {
  const { user, tokens, isLoading } = useAuth() // tokens without user means /auth/me is still running

  if (tokens && isLoading) {
    return <PageSpinner /> // stored session is being restored; do not flash the login form
  }

  if (user) {
    return <Navigate to={homePathForUser(user)} replace /> // already signed in; bounce to /candidate or /recruiter
  }

  return (
    <div className="flex min-h-svh items-center justify-center bg-background p-6">
      {/* Guest forms render here: /login or /register. A // comment in JSX would show on the page. */}
      <Outlet />
    </div>
  )
}
