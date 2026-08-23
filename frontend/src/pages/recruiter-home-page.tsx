import { useAuth } from "@/hooks/use-auth" // current user for the welcome copy + admin hint

// Recruiter landing page for Phase 3: confirms auth + role redirect. Dashboards come later.
export function RecruiterHomePage() {
  const { user } = useAuth() // RequireRole already guaranteed a recruiter

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-3">
      <h1 className="text-2xl font-semibold">Recruiter home</h1>
      <p className="text-muted-foreground">
        Signed in as {user?.email}
        {user?.isAdmin ? " (admin flag on — user management lands in Phase 14)" : ""}. Job posts, rankings, and
        reports will appear here in later phases.
      </p>
    </div>
  )
}
