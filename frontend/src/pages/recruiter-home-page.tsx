import { Link } from "react-router-dom" // Jobs + Candidates

import { Button } from "@/components/ui/button" // outline links
import { useAuth } from "@/hooks/use-auth" // current user for the welcome copy + admin hint

// Recruiter overview: ranking/compare live on Candidates. Jobs stay on /recruiter/jobs. No Interview screen.
export function RecruiterHomePage() {
  const { user } = useAuth() // RequireRole already guaranteed a recruiter

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
      <h1 className="text-2xl font-semibold">Recruiter home</h1>
      <p className="text-muted-foreground">
        Signed in as {user?.email}
        {user?.isAdmin ? " (admin flag on — user management lands in admin-ops)" : ""}. Rankings, side-by-side
        comparison, and PDF reports are on Candidates. Job postings stay on Jobs.
      </p>
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" asChild>
          <Link to="/recruiter/jobs">Open jobs</Link>
        </Button>
        <Button type="button" variant="outline" asChild>
          <Link to="/recruiter/candidates">Open candidates</Link>
        </Button>
      </div>
    </div>
  )
}
