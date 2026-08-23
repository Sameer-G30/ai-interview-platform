import { Navigate, useLocation } from "react-router-dom" // index-route redirect based on session

import { PageSpinner } from "@/components/layout/page-spinner" // wait while /auth/me restores the session
import { useAuth } from "@/hooks/use-auth" // current user + loading flags
import { homePathForUser } from "@/lib/home-path" // /candidate or /recruiter

// `/` handler: guests go to /login, signed-in users go to their role home.
export function RoleLanding() {
  const { user, tokens, isLoading } = useAuth() // decide between login and a role home
  const location = useLocation() // passed through to /login so we could restore a deep link later

  if (tokens && isLoading) {
    return <PageSpinner /> // stored session is being restored
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} /> // no session
  }

  return <Navigate to={homePathForUser(user)} replace /> // candidate or recruiter home
}
