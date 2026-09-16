import { Navigate } from "react-router-dom" // bounce non-admins off /admin/*

import { useAuth } from "@/hooks/use-auth" // current user (RequireAuth already guaranteed this is non-null)
import { homePathForUser } from "@/lib/home-path" // recruiter home; candidates never have isAdmin

// Props: the admin page tree to render when user.isAdmin is true.
type RequireAdminProps = {
  children: React.ReactNode // Users / Postings / Sessions / Scores routes
}

// Wrapper used on /admin so a recruiter without the flag (or a candidate) cannot open ops screens.
export function RequireAdmin({ children }: RequireAdminProps) {
  const { user } = useAuth() // RequireAuth is the parent, so user is set; still guard for type safety

  if (!user) {
    return <Navigate to="/login" replace /> // should not happen; belt-and-suspenders
  }

  if (!user.isAdmin) {
    return <Navigate to={homePathForUser(user)} replace /> // /recruiter or /candidate; never a third role home
  }

  return children // is_admin recruiter; render the admin layout
}
