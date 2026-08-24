import { JobQueueDemo } from "@/components/jobs/queue-demo" // Phase 4 enqueue + poll proof on the candidate home
import { useAuth } from "@/hooks/use-auth" // current user for the welcome copy

// Candidate landing: auth proof from Phase 3 plus a throwaway queue demo. Resume/interview screens come later.
export function CandidateHomePage() {
  const { user } = useAuth() // RequireRole already guaranteed a candidate

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6">
      <div className="flex flex-col gap-3">
        <h1 className="text-2xl font-semibold">Candidate home</h1>
        <p className="text-muted-foreground">
          Signed in as {user?.email}. Resume upload, parsed results, and interviews will appear here in later phases.
        </p>
      </div>
      <JobQueueDemo />
    </div>
  )
}
