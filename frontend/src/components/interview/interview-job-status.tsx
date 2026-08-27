import type { AsyncJobOut, AsyncJobStatus } from "@/api/types" // GET /jobs/{id} payload + status union

// Which worker this banner is describing; copy differs because generate and evaluate are different jobs.
export type InterviewJobKind = "generate" | "evaluate" // generate writes questions; evaluate writes the score

// Maps a job status to a short candidate-facing sentence for the given worker kind.
function labelForStatus(kind: InterviewJobKind, status: AsyncJobStatus): string {
  if (status === "queued") {
    return kind === "generate"
      ? "Queued — waiting for a worker to generate questions."
      : "Queued — waiting for a worker to score this answer."
  }
  if (status === "running") {
    return kind === "generate"
      ? "Running — the judge is writing questions from your resume."
      : "Running — the judge is scoring this answer."
  }
  if (status === "succeeded") {
    return kind === "generate" ? "Succeeded — loading questions." : "Succeeded — loading the score."
  }
  return kind === "generate"
    ? "Failed — question generation did not complete."
    : "Failed — scoring did not complete. This answer cannot be re-submitted."
}

// Queued / running / failed panel driven by useJobStatus (do not poll GET /interviews while generate is queued).
export function InterviewJobStatus({
  kind, // generate vs evaluate copy
  job, // last successful GET /jobs/{id} payload, if any
  isLoading, // true while the first poll is in flight
  pollError, // network / 404 from the poller
}: {
  kind: InterviewJobKind // which worker this card describes
  job: AsyncJobOut | undefined // undefined until the first poll returns
  isLoading: boolean // first-fetch pending
  pollError: string | null // poller failure message
}) {
  if (pollError !== null) {
    return (
      <p className="text-sm text-destructive" role="alert">
        Could not read job status: {pollError}
      </p>
    )
  }
  if (isLoading && job === undefined) {
    return <p className="text-sm text-muted-foreground">Checking {kind} job…</p> // first poll
  }
  if (job === undefined) {
    return <p className="text-sm text-muted-foreground">Waiting for a {kind} job id.</p> // missing query param
  }
  return (
    <div className="flex flex-col gap-1 text-sm">
      <p className="font-medium capitalize">{job.status}</p>
      <p className="text-muted-foreground">{labelForStatus(kind, job.status)}</p>
      {job.status === "failed" && job.error !== null ? (
        <p className="text-destructive" role="alert">
          {job.error}
        </p>
      ) : null}
    </div>
  )
}
