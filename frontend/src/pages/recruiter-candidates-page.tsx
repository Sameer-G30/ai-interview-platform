import { useMutation, useQuery } from "@tanstack/react-query" // postings + rankings + compare
import { useMemo, useState } from "react" // posting picker, filters, selected compare ids

import { listPostings, postingQueryKeys } from "@/api/postings" // owned postings for the picker
import { fetchScoreCompare, fetchScoreRankings, scoreQueryKeys } from "@/api/scores" // ranking + compare reads
import { ApiError } from "@/api/types" // FastAPI detail
import { ComparePanel } from "@/components/dashboard/compare-panel" // GET /scores/compare cards
import { RankingTable } from "@/components/dashboard/ranking-table" // stored ranking rows
import { ScoreDistributionChart } from "@/components/dashboard/score-distribution-chart" // Recharts
import { SkillDistributionChart } from "@/components/dashboard/skill-distribution-chart" // required_skills
import { Button } from "@/components/ui/button" // compare action
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // chrome
import { Input } from "@/components/ui/input" // email / min-composite filters
import { Skeleton } from "@/components/ui/skeleton" // loading
import {
  type RankingSortKey,
  compareRankingRows,
  filterRankingRows,
} from "@/lib/dashboard" // client-side sort/filter only

// Recruiter Candidates dashboard: ranking, compare, Recharts, PDF. No interview/analysis screen.
export function RecruiterCandidatesPage() {
  const [postingId, setPostingId] = useState<string>("") // empty until postings load
  const [emailQuery, setEmailQuery] = useState("") // client-side filter
  const [minCompositeText, setMinCompositeText] = useState("") // empty = no floor
  const [sortKey, setSortKey] = useState<RankingSortKey>("rank") // default = API order
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set()) // compare checkboxes
  const [compareError, setCompareError] = useState<string | null>(null) // 404/422/network

  const postingsQuery = useQuery({
    queryKey: postingQueryKeys.list(), // GET /postings
    queryFn: listPostings, // newest first
  })

  const effectivePostingId = postingId || postingsQuery.data?.[0]?.id || "" // default to newest posting
  const selectedPosting = postingsQuery.data?.find((row) => row.id === effectivePostingId) // required_skills

  const rankingsQuery = useQuery({
    queryKey: scoreQueryKeys.rankings(effectivePostingId), // GET /scores/rankings
    queryFn: () => fetchScoreRankings(effectivePostingId), // stored Score rows
    enabled: effectivePostingId !== "", // wait for a posting
    retry: false, // 404 is "not your posting"
  })

  const minComposite = minCompositeText.trim() === "" ? null : Number(minCompositeText) // NaN treated as no filter
  const minFloor = minComposite !== null && Number.isFinite(minComposite) ? minComposite : null // ignore junk

  const visibleRows = useMemo(() => {
    const rows = rankingsQuery.data?.sessions ?? [] // API composite desc
    const filtered = filterRankingRows(rows, emailQuery, minFloor) // email + min composite
    return [...filtered].sort((left, right) => compareRankingRows(left, right, sortKey)) // client-side only
  }, [rankingsQuery.data, emailQuery, minFloor, sortKey])

  const compare = useMutation({
    mutationFn: (ids: string[]) => fetchScoreCompare(ids), // GET /scores/compare
    onError: (caught) => {
      setCompareError(caught instanceof ApiError ? caught.detail : "could not compare — is the API running?")
    },
    onSuccess: () => {
      setCompareError(null) // clear a previous failure
    },
  })

  function toggleSession(sessionId: string) {
    setSelectedIds((current) => {
      const next = new Set(current) // copy
      if (next.has(sessionId)) {
        next.delete(sessionId) // uncheck
      } else {
        next.add(sessionId) // check
      }
      return next
    })
  }

  const rankingsError =
    rankingsQuery.error instanceof ApiError
      ? rankingsQuery.error.detail
      : rankingsQuery.isError
        ? "could not load rankings"
        : null

  const postingsError =
    postingsQuery.error instanceof ApiError
      ? postingsQuery.error.detail
      : postingsQuery.isError
        ? "could not load postings"
        : null

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold">Candidates</h1>
        <p className="text-muted-foreground">
          Ranking and comparison read stored scores. Practice sessions (no posting) never appear here. There is no
          recruiter interview screen.
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Posting</CardTitle>
          <CardDescription>Pick one of your postings. Other recruiters’ ids 404.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {postingsQuery.isPending ? <Skeleton className="h-10 w-full" /> : null}
          {postingsError !== null ? (
            <p className="text-sm text-destructive" role="alert">
              {postingsError}
            </p>
          ) : null}
          {postingsQuery.data !== undefined && postingsQuery.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">No postings yet — create one under Jobs.</p>
          ) : null}
          {postingsQuery.data !== undefined && postingsQuery.data.length > 0 ? (
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted-foreground">Owned posting</span>
              <select
                className="h-9 rounded-lg border border-input bg-background px-3 text-sm"
                value={effectivePostingId}
                data-testid="recruiter-posting-select"
                onChange={(event) => {
                  setPostingId(event.target.value) // refetch rankings
                  setSelectedIds(new Set()) // selection is per posting
                  compare.reset() // drop previous compare payload
                }}
              >
                {postingsQuery.data.map((posting) => (
                  <option key={posting.id} value={posting.id}>
                    {posting.title}
                    {posting.is_active ? "" : " (inactive)"}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Ranking</CardTitle>
          <CardDescription>
            Sort and filter the GET /scores/rankings payload in the browser. Composites are not recomputed.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted-foreground">Filter email</span>
              <Input
                value={emailQuery}
                onChange={(event) => {
                  setEmailQuery(event.target.value) // substring match
                }}
                placeholder="candidate@"
                data-testid="recruiter-email-filter"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted-foreground">Min composite</span>
              <Input
                type="number"
                min={0}
                max={100}
                value={minCompositeText}
                onChange={(event) => {
                  setMinCompositeText(event.target.value) // empty = no floor
                }}
                placeholder="none"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted-foreground">Sort</span>
              <select
                className="h-9 rounded-lg border border-input bg-background px-3 text-sm"
                value={sortKey}
                onChange={(event) => {
                  setSortKey(event.target.value as RankingSortKey) // client-side
                }}
              >
                <option value="rank">Rank (API)</option>
                <option value="composite">Composite</option>
                <option value="resume">Resume</option>
                <option value="technical">Technical</option>
                <option value="communication">Communication</option>
                <option value="behavioral">Behavioral</option>
                <option value="email">Email</option>
              </select>
            </label>
          </div>
          {rankingsQuery.isPending ? <Skeleton className="h-24 w-full" /> : null}
          {rankingsError !== null ? (
            <p className="text-sm text-destructive" role="alert">
              {rankingsError}
            </p>
          ) : null}
          {rankingsQuery.data !== undefined ? (
            <RankingTable rows={visibleRows} selectedIds={selectedIds} onToggle={toggleSession} />
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              disabled={selectedIds.size < 2 || compare.isPending}
              data-testid="recruiter-compare-button"
              onClick={() => {
                setCompareError(null) // clear
                compare.mutate([...selectedIds]) // ≥2 distinct ids
              }}
            >
              {compare.isPending ? "Comparing…" : "Compare selected"}
            </Button>
            <p className="text-xs text-muted-foreground">Needs two or more distinct sessions. Same id twice is 422.</p>
          </div>
          {compareError !== null ? (
            <p className="text-sm text-destructive" role="alert">
              {compareError}
            </p>
          ) : null}
          {compare.data !== undefined ? <ComparePanel scores={compare.data.sessions} /> : null}
        </CardContent>
      </Card>
      <ScoreDistributionChart rows={visibleRows} />
      <SkillDistributionChart requiredSkills={selectedPosting?.required_skills} />
    </div>
  )
}
