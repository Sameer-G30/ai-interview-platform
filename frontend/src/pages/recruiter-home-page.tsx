import { Link } from "react-router-dom" // Jobs + Candidates

import { PageHeader } from "@/components/layout/page-header" // shared title block
import { Button } from "@/components/ui/button" // outline links
import { useAuth } from "@/hooks/use-auth" // current user for the welcome copy + admin hint

// Recruiter overview: ranking/compare live on Candidates. Jobs stay on /recruiter/jobs. No Interview screen.
export function RecruiterHomePage() {
  const { user } = useAuth() // RequireRole already guaranteed a recruiter

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
      <PageHeader
        title="Recruiter home"
        description={`Signed in as ${user?.email ?? ""}${
          user?.isAdmin ? " (admin flag on — open Admin for user and posting management)" : ""
        }. Rankings, side-by-side comparison, and PDF reports are on Candidates. Job postings are on Jobs.`}
      />
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" asChild>
          <Link to="/recruiter/jobs">Open jobs</Link>
        </Button>
        <Button type="button" variant="outline" asChild>
          <Link to="/recruiter/candidates">Open candidates</Link>
        </Button>
        {user?.isAdmin ? (
          <Button type="button" variant="outline" asChild>
            <Link to="/admin">Open admin</Link>
          </Button>
        ) : null}
      </div>
    </div>
  )
}
