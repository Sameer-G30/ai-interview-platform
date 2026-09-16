import { useQuery } from "@tanstack/react-query" // GET /admin/scores — stored Score rows only

import { adminQueryKeys, listAdminScores } from "@/api/admin" // admin score audit
import { ApiError } from "@/api/types" // FastAPI detail
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // page chrome
import { Skeleton } from "@/components/ui/skeleton" // list loading placeholder
import { formatSignalScore } from "@/lib/dashboard" // omitted communication is "Not recorded", never 0

// Format ISO timestamps from FastAPI for the score table.
function formatWhen(iso: string | null): string {
  if (iso === null) {
    return "—" // should be rare; completed_at is set when evaluate flips the session
  }
  const date = new Date(iso) // browser-local
  if (Number.isNaN(date.getTime())) {
    return iso // fallback to the raw string
  }
  return date.toLocaleString() // short local stamp
}

// Admin Scores: stored composites including practice. Does not call ml.scoring or Ollama.
export function AdminScoresPage() {
  const scoresQuery = useQuery({
    queryKey: adminQueryKeys.scores(), // GET /admin/scores
    queryFn: listAdminScores, // composite present; in_progress omitted
  })

  const scoresError =
    scoresQuery.error instanceof ApiError
      ? scoresQuery.error.detail
      : scoresQuery.isError
        ? "could not load scores — is the API running?"
        : null

  return (
    <Card data-testid="admin-scores">
      <CardHeader>
        <CardTitle>Scores</CardTitle>
        <CardDescription>
          Stored Score rows only. Practice sessions appear here (ops). Communication stays “Not recorded” when the
          signal was omitted — never charted as 0.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {scoresQuery.isPending ? <Skeleton className="h-24 w-full" /> : null}
        {scoresError !== null ? (
          <p className="text-sm text-destructive" role="alert">
            {scoresError}
          </p>
        ) : null}
        {scoresQuery.data !== undefined && scoresQuery.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">No stored composites yet.</p>
        ) : null}
        {scoresQuery.data !== undefined && scoresQuery.data.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[48rem] text-left text-sm">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">Completed</th>
                  <th className="py-2 pr-3 font-medium">Candidate</th>
                  <th className="py-2 pr-3 font-medium">Kind</th>
                  <th className="py-2 pr-3 font-medium">Resume</th>
                  <th className="py-2 pr-3 font-medium">Technical</th>
                  <th className="py-2 pr-3 font-medium">Communication</th>
                  <th className="py-2 pr-3 font-medium">Behavioral</th>
                  <th className="py-2 font-medium">Composite</th>
                </tr>
              </thead>
              <tbody>
                {scoresQuery.data.map((row) => (
                  <tr key={row.session_id} className="border-b border-border last:border-0">
                    <td className="py-2 pr-3 tabular-nums">{formatWhen(row.completed_at)}</td>
                    <td className="py-2 pr-3">{row.candidate_email}</td>
                    <td className="py-2 pr-3">{row.job_id === null ? "Practice" : (row.posting_title ?? "Posting")}</td>
                    <td className="py-2 pr-3 tabular-nums">{formatSignalScore(row.resume_score)}</td>
                    <td className="py-2 pr-3 tabular-nums">{formatSignalScore(row.technical_score)}</td>
                    <td className="py-2 pr-3 tabular-nums">{formatSignalScore(row.communication_score)}</td>
                    <td className="py-2 pr-3 tabular-nums">{formatSignalScore(row.behavioral_score)}</td>
                    <td className="py-2 tabular-nums">{formatSignalScore(row.composite_score)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
