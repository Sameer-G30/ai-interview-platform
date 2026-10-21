import type { AsyncJobOut, AsyncJobStatus } from "@/api/types" // GET /jobs/{id} payload + status union

// Maps a job status to a short candidate-facing sentence.
function labelForStatus(status: AsyncJobStatus): string {
  if (status === "queued") {
    return "Waiting to start reading your resume."
  }
  if (status === "running") {
    return "Reading your resume and matching skills."
  }
  if (status === "succeeded") {
    return "Done. Loading your results."
  }
  return "We could not read this resume."
}

// Queued / running / failed panel driven by useJobStatus (do not poll GET /resumes here).
export function ParseStatus({
  job, // last successful GET /jobs/{id} payload, if any
  isLoading, // true while the first poll is in flight
  pollError, // network / 404 from the poller
}: {
  job: AsyncJobOut | undefined // undefined until the first poll returns
  isLoading: boolean // first-fetch pending
  pollError: string | null // poller failure message
}) {
  if (pollError !== null) {
    return (
      <p className="text-sm text-destructive" role="alert">
        Could not check progress: {pollError}
      </p>
    )
  }
  if (isLoading && job === undefined) {
    return <p className="text-sm text-muted-foreground">Checking progress…</p>
  }
  if (job === undefined) {
    return <p className="text-sm text-muted-foreground">Waiting to start.</p>
  }
  return (
    <div className="flex flex-col gap-1 text-sm">
      <p className="text-muted-foreground">{labelForStatus(job.status)}</p>
      {job.status === "failed" && job.error !== null ? (
        <p className="text-destructive" role="alert">
          {job.error}
        </p>
      ) : null}
    </div>
  )
}
