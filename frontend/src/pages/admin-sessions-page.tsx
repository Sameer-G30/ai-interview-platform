import { useQuery } from "@tanstack/react-query" // GET /admin/sessions — stored rows only
import { useState } from "react" // optional status filter

import { adminQueryKeys, listAdminSessions } from "@/api/admin" // admin session audit
import { ApiError } from "@/api/types" // FastAPI detail
import type { InterviewSessionStatus } from "@/api/types" // filter values
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // page chrome
import { Skeleton } from "@/components/ui/skeleton" // list loading placeholder
import { formatSessionStatus, formatSignalScore } from "@/lib/dashboard" // same labels as candidate history

// Format ISO timestamps from FastAPI for the audit table.
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

// Admin Sessions: every candidate, practice included. Not GET /interviews (that is the caller's own history).
export function AdminSessionsPage() {
  const [status, setStatus] = useState<InterviewSessionStatus | "">("") // empty = no filter

  const params = {
    status: status === "" ? undefined : status, // query alias `status` on the API
  }

  const sessionsQuery = useQuery({
    queryKey: adminQueryKeys.sessions(params), // GET /admin/sessions
    queryFn: () => listAdminSessions(params), // newest created_at first
  })

  const sessionsError =
    sessionsQuery.error instanceof ApiError
      ? sessionsQuery.error.detail
      : sessionsQuery.isError
        ? "could not load sessions — is the API running?"
        : null

  return (
    <Card data-testid="admin-sessions">
      <CardHeader>
        <CardTitle>Sessions</CardTitle>
        <CardDescription>
          Ops listing across candidates. Practice (no posting) is included here; recruiter ranking still omits it.
          Composites are stored values — this page does not recompute.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <label className="flex max-w-xs flex-col gap-1 text-sm">
          <span className="text-muted-foreground">Status</span>
          <select
            className="h-9 rounded-lg border border-input bg-background px-3 text-sm"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as InterviewSessionStatus | "") // refetch
            }}
          >
            <option value="">All statuses</option>
            <option value="scheduled">Scheduled</option>
            <option value="in_progress">In progress</option>
            <option value="completed">Completed</option>
            <option value="abandoned">Abandoned</option>
          </select>
        </label>
        {sessionsQuery.isPending ? <Skeleton className="h-24 w-full" /> : null}
        {sessionsError !== null ? (
          <p className="text-sm text-destructive" role="alert">
            {sessionsError}
          </p>
        ) : null}
        {sessionsQuery.data !== undefined && sessionsQuery.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">No sessions match these filters.</p>
        ) : null}
        {sessionsQuery.data !== undefined && sessionsQuery.data.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[40rem] text-left text-sm">
              <thead>
                <tr className="border-b border-border text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">When</th>
                  <th className="py-2 pr-3 font-medium">Candidate</th>
                  <th className="py-2 pr-3 font-medium">Kind</th>
                  <th className="py-2 pr-3 font-medium">Status</th>
                  <th className="py-2 font-medium">Composite</th>
                </tr>
              </thead>
              <tbody>
                {sessionsQuery.data.map((row) => (
                  <tr key={row.id} className="border-b border-border last:border-0">
                    <td className="py-2 pr-3 tabular-nums">{formatWhen(row.created_at)}</td>
                    <td className="py-2 pr-3">{row.candidate_email}</td>
                    <td className="py-2 pr-3">{row.job_id === null ? "Practice" : (row.posting_title ?? "Posting")}</td>
                    <td className="py-2 pr-3">{formatSessionStatus(row.status)}</td>
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
