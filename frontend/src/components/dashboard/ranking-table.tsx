import type { RankingRowOut } from "@/api/types" // GET /scores/rankings payload
import { DownloadReportButton } from "@/components/interview/download-report" // GET /reports/{id} + apiBlob
import { formatSignalScore } from "@/lib/dashboard" // omitted ≠ 0

// Recruiter ranking table: stored scores only. Sort/filter happen in the parent from this payload.
export function RankingTable({
  rows,
  selectedIds,
  onToggle,
}: {
  rows: RankingRowOut[] // already filtered/sorted client-side
  selectedIds: Set<string> // session ids queued for GET /scores/compare
  onToggle: (sessionId: string) => void // checkbox
}) {
  return (
    <div className="overflow-x-auto" data-testid="recruiter-ranking-table">
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">No ranked sessions match this posting and filter.</p>
      ) : (
        <table className="w-full min-w-[52rem] text-left text-sm">
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th className="py-2 pr-2 font-medium">Compare</th>
              <th className="py-2 pr-2 font-medium">Rank</th>
              <th className="py-2 pr-2 font-medium">Candidate</th>
              <th className="py-2 pr-2 font-medium">Composite</th>
              <th className="py-2 pr-2 font-medium">Resume</th>
              <th className="py-2 pr-2 font-medium">Technical</th>
              <th className="py-2 pr-2 font-medium">Communication</th>
              <th className="py-2 pr-2 font-medium">Behavioral</th>
              <th className="py-2 font-medium">Report</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.session_id} className="border-b border-border last:border-0">
                <td className="py-2 pr-2">
                  <input
                    type="checkbox"
                    aria-label={`Select ${row.candidate_email} for comparison`}
                    checked={selectedIds.has(row.session_id)}
                    onChange={() => {
                      onToggle(row.session_id) // parent owns the Set
                    }}
                  />
                </td>
                <td className="py-2 pr-2 tabular-nums">{row.rank}</td>
                <td className="py-2 pr-2">{row.candidate_email}</td>
                <td className="py-2 pr-2 tabular-nums">{formatSignalScore(row.composite_score)}</td>
                <td className="py-2 pr-2 tabular-nums">{formatSignalScore(row.resume_score)}</td>
                <td className="py-2 pr-2 tabular-nums">{formatSignalScore(row.technical_score)}</td>
                <td className="py-2 pr-2 tabular-nums">{formatSignalScore(row.communication_score)}</td>
                <td className="py-2 pr-2 tabular-nums">{formatSignalScore(row.behavioral_score)}</td>
                <td className="py-2">
                  <DownloadReportButton sessionId={row.session_id} compact />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
