import { Link } from "react-router-dom" // /candidate/interview/:sessionId

import type { InterviewSessionListItemOut } from "@/api/types" // GET /interviews rows
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // history chrome
import { formatSessionKind, formatSessionStatus, formatSignalScore } from "@/lib/dashboard" // practice vs posting

// Format ISO timestamps from FastAPI for the history table (empty when still scheduled).
function formatWhen(iso: string | null): string {
  if (iso === null) {
    return "—" // not started / not completed
  }
  const date = new Date(iso) // browser-local
  if (Number.isNaN(date.getTime())) {
    return iso // fallback to the raw string
  }
  return date.toLocaleString() // short local stamp
}

// Candidate interview history: completed / in_progress / abandoned, practice vs posting, link to session.
export function InterviewHistoryCard({ sessions }: { sessions: InterviewSessionListItemOut[] }) {
  return (
    <Card data-testid="candidate-history">
      <CardHeader>
        <CardTitle>Interview history</CardTitle>
        <CardDescription>Newest first. Practice sessions stay here; recruiters never rank them.</CardDescription>
      </CardHeader>
      <CardContent>
        {sessions.length === 0 ? (
          <p className="text-sm text-muted-foreground">No sessions yet. Start a practice interview or pick a match.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] text-left text-sm">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">When</th>
                  <th className="py-2 pr-3 font-medium">Kind</th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 pr-3 font-medium">Composite</th>
                  <th className="py-2 font-medium">Open</th>
                </tr>
              </thead>
              <tbody>
                {sessions.map((row) => (
                  <tr key={row.id} className="border-b border-border last:border-0">
                    <td className="py-2 pr-3 tabular-nums">{formatWhen(row.created_at)}</td>
                    <td className="py-2 pr-3">{formatSessionKind(row)}</td>
                    <td className="py-2 pr-3">{formatSessionStatus(row.status)}</td>
                    <td className="py-2 pr-3 tabular-nums">{formatSignalScore(row.composite_score)}</td>
                    <td className="py-2">
                      <Link className="font-medium underline underline-offset-4" to={`/candidate/interview/${row.id}`}>
                        Session
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
