import type { AsyncJobOut, AsyncJobStatus } from "@/api/types" // GET /jobs/{id} payload + status union

// Maps a job status to a short candidate-facing sentence.
function labelForStatus(status: AsyncJobStatus): string {
  if (status === "queued") {
    return "Queued — waiting for a worker." // Redis has the job; ARQ has not started it
  }
  if (status === "running") {
    return "Running — extracting text, skills, and ATS score." // worker is inside resume_parse
  }
  if (status === "succeeded") {
    return "Succeeded — loading parsed results." // parent will GET /resumes/{id}
  }
  return "Failed — parsing did not complete." // terminal error; details come from job.error
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
        Could not read job status: {pollError}
      </p>
    )
  }
  if (isLoading && job === undefined) {
    return <p className="text-sm text-muted-foreground">Checking parse job…</p> // first poll
  }
  if (job === undefined) {
    return <p className="text-sm text-muted-foreground">Waiting for a parse job id.</p> // missing ?job=
  }
  return (
    <div className="flex flex-col gap-1 text-sm">
      <p className="font-medium capitalize">{job.status}</p>
      <p className="text-muted-foreground">{labelForStatus(job.status)}</p>
      {job.status === "failed" && job.error !== null ? (
        <p className="text-destructive" role="alert">
          {job.error}
        </p>
      ) : null}
    </div>
  )
}
