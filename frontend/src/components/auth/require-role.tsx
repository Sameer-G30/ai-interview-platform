import { Navigate } from "react-router-dom" // bounce the user to their own home when the role does not match

import type { UserRole } from "@/api/types" // "candidate" | "recruiter"
import { useAuth } from "@/hooks/use-auth" // current user (RequireAuth already guaranteed this is non-null)
import { homePathForUser } from "@/lib/home-path" // fallback path when a candidate hits /recruiter or vice versa

// Props: the role this route is for, plus the page to render when the role matches.
type RequireRoleProps = {
  role: UserRole // "candidate" or "recruiter" — admin is a flag, not a route tree
  children: React.ReactNode // the page element to render when the signed-in user has this role
}

// Wrapper used on /candidate and /recruiter so a user cannot view the other persona's home.
export function RequireRole({ role, children }: RequireRoleProps) {
  const { user } = useAuth() // RequireAuth is the parent, so user is set; still guard for type safety

  if (!user) {
    return <Navigate to="/login" replace /> // should not happen; belt-and-suspenders
  }

  if (user.role !== role) {
    return <Navigate to={homePathForUser(user)} replace /> // send them to their own home instead of 403ing
  }

  return children // role matches; render the page
}
