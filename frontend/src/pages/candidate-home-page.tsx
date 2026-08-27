import { Link } from "react-router-dom" // in-app link to the Phase 6 resume upload screen

import { JobQueueDemo } from "@/components/jobs/queue-demo" // Phase 4 enqueue + poll proof; keep this card
import { Button } from "@/components/ui/button" // outline link styled as a button; do not restyle the primitive
import { useAuth } from "@/hooks/use-auth" // current user for the welcome copy

// Candidate landing: auth proof from Phase 3, queue demo from Phase 4, link to Phase 6 resume upload.
export function CandidateHomePage() {
  const { user } = useAuth() // RequireRole already guaranteed a candidate

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6">
      <div className="flex flex-col gap-3">
        <h1 className="text-2xl font-semibold">Candidate home</h1>
        <p className="text-muted-foreground">
          Signed in as {user?.email}. Upload a PDF resume, review Matches, then start a practice interview or one
          against a posting.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" asChild>
            <Link to="/candidate/resume">Open resume upload</Link>
          </Button>
          <Button type="button" variant="outline" asChild>
            <Link to="/candidate/interview">Open interview</Link>
          </Button>
        </div>
      </div>
      <JobQueueDemo />
    </div>
  )
}
