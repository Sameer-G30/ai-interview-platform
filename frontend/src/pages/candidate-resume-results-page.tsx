import { useQuery } from "@tanstack/react-query" // one GET /resumes/{id} after the job is terminal
import { Link, useParams, useSearchParams } from "react-router-dom" // resume id from the path; job id from ?job=

import { ApiError } from "@/api/types" // poll / GET failures
import { fetchResume, resumeQueryKeys } from "@/api/resumes" // GET /resumes/{id}
import { ParseStatus } from "@/components/resume/parse-status" // queued / running / failed from useJobStatus
import { ResumeResults } from "@/components/resume/resume-results" // ATS + skills + sections
import { Button } from "@/components/ui/button" // back / retry links
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // status chrome
import { Skeleton } from "@/components/ui/skeleton" // pending results placeholder
import { useJobStatus } from "@/hooks/use-job-status" // existing poller; do not write a second one

// Candidate parsed-results page: poll GET /jobs/{id}, then GET /resumes/{id} once the job is terminal.
export function CandidateResumeResultsPage() {
  const { resumeId } = useParams() // /candidate/resume/:resumeId
  const [params] = useSearchParams() // ?job=<async_job_id> from the upload redirect
  const jobId = params.get("job") // null if the user opened the results URL without a job query
  const jobQuery = useJobStatus(jobId) // disabled when jobId is null
  const jobStatus = jobQuery.data?.status // queued | running | succeeded | failed | undefined
  const jobTerminal = jobStatus === "succeeded" || jobStatus === "failed" // stop waiting on the poller
  const canFetchResume = resumeId !== undefined && (jobId === null || jobTerminal) // no job id → still try GET

  const resumeQuery = useQuery({
    queryKey: resumeId === undefined ? resumeQueryKeys.all : resumeQueryKeys.detail(resumeId), // idle key unused
    queryFn: () => fetchResume(resumeId as string), // enabled-gate guarantees resumeId is set
    enabled: canFetchResume, // do not GET /resumes until the job succeeded/failed (or there is no job id)
    staleTime: 0, // results must not look fresh while we just transitioned from running
  })

  const pollError =
    jobQuery.error instanceof ApiError ? jobQuery.error.detail : jobQuery.isError ? jobQuery.error.message : null // poller error copy
  const resumeError =
    resumeQuery.error instanceof ApiError
      ? resumeQuery.error.detail
      : resumeQuery.isError
        ? resumeQuery.error.message
        : null // GET /resumes error copy

  if (resumeId === undefined) {
    return (
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
        <p className="text-sm text-destructive" role="alert">
          Missing resume id.
        </p>
        <Button type="button" variant="outline" asChild>
          <Link to="/candidate/resume">Upload a resume</Link>
        </Button>
      </div>
    )
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold">Parsed resume</h1>
        <p className="text-muted-foreground">
          Job status comes from GET /jobs/{"{id}"}. Parsed sections, skills, and ATS score come from GET
          /resumes/{"{id}"} after the job finishes.
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Parse job</CardTitle>
          <CardDescription>
            {jobId !== null ? `Polling ${jobId}` : "No job id in the URL — reading the resume row directly."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {jobId !== null ? (
            <ParseStatus
              job={jobQuery.data}
              isLoading={jobQuery.isPending}
              pollError={pollError}
            />
          ) : (
            <p className="text-sm text-muted-foreground">Skipped job polling because ?job= is missing.</p>
          )}
        </CardContent>
      </Card>
      {jobStatus === "queued" || jobStatus === "running" || (jobQuery.isPending && jobId !== null && !jobTerminal) ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <p className="text-sm text-muted-foreground">Waiting for the worker to finish…</p>
        </div>
      ) : null}
      {canFetchResume && resumeQuery.isPending ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-32 w-full" />
          <p className="text-sm text-muted-foreground">Loading parsed results…</p>
        </div>
      ) : null}
      {resumeError !== null ? (
        <p className="text-sm text-destructive" role="alert">
          Could not load resume: {resumeError}
        </p>
      ) : null}
      {resumeQuery.data !== undefined ? <ResumeResults resume={resumeQuery.data} /> : null}
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" asChild>
          <Link to="/candidate/resume">Upload another</Link>
        </Button>
        <Button type="button" variant="outline" asChild>
          <Link to="/candidate">Back to overview</Link>
        </Button>
      </div>
    </div>
  )
}
