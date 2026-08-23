import type { CurrentUser } from "@/api/types" // needs role to pick the post-login landing route

// Role-aware home path: candidates land on /candidate, recruiters (including admins) on /recruiter.
export function homePathForUser(user: CurrentUser): string {
  if (user.role === "recruiter") {
    return "/recruiter" // recruiters and is_admin recruiters share this home; there is no /admin yet
  }
  return "/candidate" // every other authenticated user is a candidate
}
