import { useQuery } from "@tanstack/react-query" // history, matches, score — dashboard reads only
import { Link } from "react-router-dom" // resume / interview CTAs

import { listInterviews, interviewQueryKeys } from "@/api/interviews" // GET /interviews candidate history
import { fetchMatches, matchQueryKeys } from "@/api/matches" // GET /matches skill-gap chips
import { fetchScore, scoreQueryKeys } from "@/api/scores" // GET /scores/{id} stored composite
import { ApiError } from "@/api/types" // 404 = no parsed resume on matches
import { InterviewHistoryCard } from "@/components/dashboard/interview-history" // session table
import { RecommendationsCard } from "@/components/dashboard/recommendations-card" // derived coaching
import { ScoreSummaryCard, ScoreSummaryEmpty } from "@/components/dashboard/score-summary" // four signals
import { SkillGapCard } from "@/components/dashboard/skill-gap-card" // GET /matches
import { JobQueueDemo } from "@/components/jobs/queue-demo" // Phase 4 enqueue + poll proof; keep this card
import { Button } from "@/components/ui/button" // outline links
import { Skeleton } from "@/components/ui/skeleton" // loading placeholders
import { useAuth } from "@/hooks/use-auth" // welcome email
import {
  buildRecommendations,
  hasInProgressWithoutScore,
  latestCompletedSession,
} from "@/lib/dashboard" // empty-state helpers

// Candidate dashboard: stored Score summary, history, skill-gap, recommendations. Keep Resume/Matches/Interview.
export function CandidateHomePage() {
  const { user } = useAuth() // RequireRole already guaranteed a candidate

  const historyQuery = useQuery({
    queryKey: interviewQueryKeys.list(), // GET /interviews
    queryFn: listInterviews, // newest first
  })

  const matchesQuery = useQuery({
    queryKey: matchQueryKeys.forResume(), // latest parsed resume
    queryFn: () => fetchMatches(), // reuse the product matcher
    retry: false, // 404 is the empty state
  })

  const noParsedResume = matchesQuery.error instanceof ApiError && matchesQuery.error.status === 404 // upload CTA
  const completed = latestCompletedSession(historyQuery.data) // featured Score
  const scoreQuery = useQuery({
    queryKey: scoreQueryKeys.detail(completed?.id ?? "none"), // skip until we have an id
    queryFn: () => fetchScore(completed!.id), // stored row only
    enabled: completed !== undefined, // in_progress has no Score
    retry: false, // 404 is a real empty state
  })

  const historyError =
    historyQuery.error instanceof ApiError
      ? historyQuery.error.detail
      : historyQuery.isError
        ? "could not load interview history — is the API running?"
        : null

  const inProgress = hasInProgressWithoutScore(historyQuery.data) // banner + recommendation
  const recommendations = buildRecommendations({
    noParsedResume, // matches 404
    hasSessions: (historyQuery.data?.length ?? 0) > 0, // GET /interviews
    inProgressWithoutScore: inProgress, // open session, no composite
    matches: noParsedResume ? undefined : matchesQuery.data?.matches, // chips
    latestScore: scoreQuery.data ?? null, // GET /scores/{id}
  })

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <div className="flex flex-col gap-3">
        <h1 className="text-2xl font-semibold">Candidate dashboard</h1>
        <p className="text-muted-foreground">
          Signed in as {user?.email}. Scores are stored composites (not recomputed here). Communication stays “Not
          recorded” on text-only sessions.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" asChild>
            <Link to="/candidate/resume">Open resume upload</Link>
          </Button>
          <Button type="button" variant="outline" asChild>
            <Link to="/candidate/matches">Open matches</Link>
          </Button>
          <Button type="button" variant="outline" asChild>
            <Link to="/candidate/interview">Open interview</Link>
          </Button>
        </div>
      </div>
      {historyQuery.isPending || (completed !== undefined && scoreQuery.isPending) ? (
        <Skeleton className="h-40 w-full" />
      ) : null}
      {historyError !== null ? (
        <p className="text-sm text-destructive" role="alert">
          {historyError}
        </p>
      ) : null}
      {noParsedResume ? (
        <ScoreSummaryEmpty
          title="No parsed resume yet"
          body="Upload a PDF so ATS, matches, and interviews can run. There is no composite until you complete a session."
        />
      ) : null}
      {!noParsedResume && historyQuery.data !== undefined && historyQuery.data.length === 0 ? (
        <ScoreSummaryEmpty
          title="No sessions yet"
          body="Start a practice interview or pick a posting on Matches. A composite appears after evaluate completes the session."
        />
      ) : null}
      {!noParsedResume && inProgress && completed === undefined ? (
        <ScoreSummaryEmpty
          title="Interview in progress"
          body="This session has no stored Score yet. Finish answering — GET /scores/{id} 404s until the session is completed."
        />
      ) : null}
      {scoreQuery.data !== undefined && completed !== undefined ? (
        <ScoreSummaryCard score={scoreQuery.data} sessionPath={`/candidate/interview/${completed.id}`} />
      ) : null}
      {historyQuery.data !== undefined ? <InterviewHistoryCard sessions={historyQuery.data} /> : null}
      <SkillGapCard noParsedResume={noParsedResume} matches={noParsedResume ? undefined : matchesQuery.data?.matches} />
      <RecommendationsCard items={recommendations} />
      <JobQueueDemo />
    </div>
  )
}
