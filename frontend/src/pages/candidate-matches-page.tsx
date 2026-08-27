import { useMutation, useQuery } from "@tanstack/react-query" // GET /matches + POST /interviews from a card
import { useState } from "react" // per-card start error
import { Link, useNavigate } from "react-router-dom" // upload CTA; session URL after 201

import { interviewSessionPath, startInterview } from "@/api/interviews" // start with this posting's job_id
import { fetchMatches, matchQueryKeys } from "@/api/matches" // typed /matches client
import { ApiError } from "@/api/types" // status-based branching (404 = no parsed resume yet)
import type { MatchOut } from "@/api/types" // one ranked posting
import { Button } from "@/components/ui/button" // link to the resume upload page + start interview
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // page chrome
import { Skeleton } from "@/components/ui/skeleton" // loading placeholder

// Skill chip row shared by matched (positive) and missing (negative) skills.
function SkillChipList({ skills, variant }: { skills: string[]; variant: "matched" | "missing" }) {
  if (skills.length === 0) {
    return null
  }
  const chipClass =
    variant === "matched"
      ? "border-primary/30 bg-primary/10 text-primary"
      : "border-destructive/30 bg-destructive/10 text-destructive"
  return (
    <ul className="flex flex-wrap gap-1.5">
      {skills.map((skill) => (
        <li key={skill} className={`rounded-full border px-2 py-0.5 text-xs font-medium ${chipClass}`}>
          {skill}
        </li>
      ))}
    </ul>
  )
}

// One ranked posting card: title, similarity score, matched/missing skill chips, Start interview action.
function MatchCard({ match, resumeId }: { match: MatchOut; resumeId: string }) {
  const navigate = useNavigate() // after 201, keep session_id + async_job_id in the URL like resume results
  const [error, setError] = useState<string | null>(null) // 409 inactive posting / network
  const percent = Math.round(Math.max(0, Math.min(1, match.score)) * 100) // clamp: cosine sim can dip below 0

  const start = useMutation({
    mutationFn: () => startInterview({ resume_id: resumeId, job_id: match.posting_id }), // posting-targeted session
    onSuccess: (body) => {
      navigate(interviewSessionPath(body.session_id, body.async_job_id)) // poll generate, then GET session
    },
    onError: (caught) => {
      if (caught instanceof ApiError) {
        setError(caught.detail) // 409 inactive, 404 posting, 429
        return // stay on Matches
      }
      setError("could not start an interview — is the API running?") // network
    },
  })

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>{match.title}</CardTitle>
        <CardDescription>Match score {percent}%</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="h-1.5 overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-primary" style={{ width: `${percent}%` }} />
        </div>
        {match.matched_skills.length > 0 ? (
          <div className="flex flex-col gap-1">
            <p className="text-xs text-muted-foreground">You have</p>
            <SkillChipList skills={match.matched_skills} variant="matched" />
          </div>
        ) : null}
        {match.missing_skills.length > 0 ? (
          <div className="flex flex-col gap-1">
            <p className="text-xs text-muted-foreground">Skill gap</p>
            <SkillChipList skills={match.missing_skills} variant="missing" />
          </div>
        ) : null}
        {match.matched_skills.length === 0 && match.missing_skills.length === 0 ? (
          <p className="text-xs text-muted-foreground">This posting listed no required skills.</p>
        ) : null}
        {error !== null ? (
          <p className="text-xs text-destructive" role="alert">
            {error}
          </p>
        ) : null}
        <Button
          type="button"
          size="sm"
          disabled={start.isPending}
          data-testid={`start-interview-${match.posting_id}`}
          onClick={() => {
            setError(null) // clear a previous API error before retrying
            start.mutate() // POST /interviews { resume_id, job_id }
          }}
        >
          {start.isPending ? "Starting…" : "Start interview"}
        </Button>
      </CardContent>
    </Card>
  )
}

// Candidate-only Matches page: ranks active postings against the caller's latest parsed resume.
export function CandidateMatchesPage() {
  const matchesQuery = useQuery({
    queryKey: matchQueryKeys.forResume(),
    queryFn: () => fetchMatches(),
    retry: false, // a 404 (no parsed resume) is an expected empty state, not a transient failure to retry
  })

  const noParsedResume = matchesQuery.error instanceof ApiError && matchesQuery.error.status === 404
  const otherError =
    matchesQuery.isError && !noParsedResume
      ? matchesQuery.error instanceof ApiError
        ? matchesQuery.error.detail
        : "could not load matches — is the API running?"
      : null

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold">Matches</h1>
        <p className="text-muted-foreground">
          Ranked by SBERT similarity between your latest parsed resume and every active job posting.
        </p>
      </div>
      {matchesQuery.isPending ? (
        <div className="flex flex-col gap-3">
          <Skeleton className="h-28 w-full" />
          <Skeleton className="h-28 w-full" />
        </div>
      ) : null}
      {noParsedResume ? (
        <Card>
          <CardHeader>
            <CardTitle>No parsed resume yet</CardTitle>
            <CardDescription>Upload and parse a resume first, then come back to see your matches.</CardDescription>
          </CardHeader>
          <CardContent>
            <Button type="button" asChild>
              <Link to="/candidate/resume">Upload a resume</Link>
            </Button>
          </CardContent>
        </Card>
      ) : null}
      {otherError !== null ? (
        <p className="text-sm text-destructive" role="alert">
          Could not load matches: {otherError}
        </p>
      ) : null}
      {matchesQuery.data !== undefined ? (
        matchesQuery.data.matches.length === 0 ? (
          <p className="text-sm text-muted-foreground">No active postings are embedded yet — check back soon.</p>
        ) : (
          <div className="flex flex-col gap-4">
            {matchesQuery.data.matches.map((match) => (
              <MatchCard key={match.posting_id} match={match} resumeId={matchesQuery.data.resume_id} />
            ))}
          </div>
        )
      ) : null}
    </div>
  )
}
