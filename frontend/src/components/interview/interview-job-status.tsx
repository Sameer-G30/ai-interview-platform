import type { AsyncJobOut, AsyncJobStatus } from "@/api/types" // GET /jobs/{id} payload + status union

// Which worker this banner is describing; copy differs because generate and evaluate are different jobs.
export type InterviewJobKind = "generate" | "evaluate" | "transcribe" // generate / judge / Whisper

// Maps a job status to a short candidate-facing sentence for the given worker kind.
function labelForStatus(kind: InterviewJobKind, status: AsyncJobStatus): string {
  if (status === "queued") {
    if (kind === "generate") {
      return "Waiting to write your questions."
    }
    if (kind === "evaluate") {
      return "Waiting to score this answer."
    }
    return "Waiting to transcribe this recording."
  }
  if (status === "running") {
    if (kind === "generate") {
      return "Writing questions from your resume."
    }
    if (kind === "evaluate") {
      return "Scoring this answer."
    }
    return "Transcribing your recording."
  }
  if (status === "succeeded") {
    if (kind === "generate") {
      return "Questions are ready."
    }
    if (kind === "evaluate") {
      return "Score is ready."
    }
    return "Transcript is ready."
  }
  if (kind === "generate") {
    return "We could not write questions for this session."
  }
  if (kind === "evaluate") {
    return "Scoring did not complete. Record this answer again."
  }
  return "Transcription did not complete. Record this answer again."
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
      <p className="text-muted-foreground">{labelForStatus(kind, job.status)}</p>
      {job.status === "failed" && job.error !== null ? (
        <p className="text-destructive" role="alert">
          {job.error}
        </p>
      ) : null}
    </div>
  )
}
