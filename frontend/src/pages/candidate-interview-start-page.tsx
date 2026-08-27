import { useMutation } from "@tanstack/react-query" // one-shot POST /interviews
import { useState } from "react" // API error banner
import { Link, useNavigate } from "react-router-dom" // resume CTA; session URL after 201

import { interviewSessionPath, startInterview } from "@/api/interviews" // practice start with {}
import { ApiError } from "@/api/types" // 404 no parsed resume / 409 not-yet-parsed
import { Button } from "@/components/ui/button" // start + resume link; do not restyle the primitive
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // page chrome

// Candidate-only Interview landing: practice start (latest parsed resume, no posting). Recruiter has no route here.
export function CandidateInterviewStartPage() {
  const navigate = useNavigate() // after 201, keep session_id + async_job_id in the URL like resume results
  const [error, setError] = useState<string | null>(null) // generic API failures
  const [emptyResume, setEmptyResume] = useState(false) // GET-style 404: no parsed resume yet
  const [pendingResume, setPendingResume] = useState(false) // 409: owned resume not yet parsed

  const start = useMutation({
    mutationFn: () => startInterview({}), // omit resume_id and job_id — latest parsed resume, practice
    onSuccess: (body) => {
      navigate(interviewSessionPath(body.session_id, body.async_job_id)) // poll generate, then GET session
    },
    onError: (caught) => {
      setEmptyResume(false) // reset both empty states; the status below picks one
      setPendingResume(false)
      if (caught instanceof ApiError && caught.status === 404) {
        setEmptyResume(true) // same empty state as Matches: upload a resume first
        return // stay on this page
      }
      if (caught instanceof ApiError && caught.status === 409) {
        setPendingResume(true) // owned but still parsing
        return // stay on this page
      }
      if (caught instanceof ApiError) {
        setError(caught.detail) // inactive posting / 429 / 503
        return // stay on this page
      }
      setError("could not start an interview — is the API running?") // network
    },
  })

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold">Interview</h1>
        <p className="text-muted-foreground">
          Start a practice interview from your latest parsed resume, or open Matches and start one against a posting.
          Recruiters do not have this screen.
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Practice interview</CardTitle>
          <CardDescription>
            POST /interviews with an empty body. Question generation runs on the ARQ worker — this page only enqueues.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {emptyResume ? (
            <div className="flex flex-col gap-2">
              <p className="text-sm text-muted-foreground">
                No parsed resume yet. Upload and parse a resume first, then start an interview.
              </p>
              <Button type="button" asChild>
                <Link to="/candidate/resume">Upload a resume</Link>
              </Button>
            </div>
          ) : null}
          {pendingResume ? (
            <p className="text-sm text-muted-foreground">
              That resume is still parsing. Wait until the Resume page shows a score, then try again.
            </p>
          ) : null}
          {error !== null ? (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              disabled={start.isPending}
              data-testid="start-practice-interview"
              onClick={() => {
                setError(null) // clear a previous API error before retrying
                setEmptyResume(false)
                setPendingResume(false)
                start.mutate() // POST /interviews {}
              }}
            >
              {start.isPending ? "Starting…" : "Start practice interview"}
            </Button>
            <Button type="button" variant="outline" asChild>
              <Link to="/candidate/matches">Start from Matches</Link>
            </Button>
            <Button type="button" variant="outline" asChild>
              <Link to="/candidate">Back to overview</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
