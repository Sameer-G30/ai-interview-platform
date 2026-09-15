import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts" // plan Part 3

import type { RankingRowOut } from "@/api/types" // GET /scores/rankings rows; do not re-aggregate
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // chrome
import { SIGNAL_LABELS } from "@/lib/dashboard" // four signals after coding dropped

// Short label so long emails do not blow the X axis on a phone.
function shortEmail(email: string): string {
  const local = email.split("@")[0] ?? email // part before @
  if (local.length <= 12) {
    return local // fits
  }
  return `${local.slice(0, 11)}…` // truncate
}

// One chart row: composite plus optional signal values (undefined = omit, not 0).
type ChartRow = {
  name: string // short email
  composite: number // always present on ranking rows
  resume?: number // omitted if null
  technical?: number // omitted if null
  communication?: number // omitted if null (text-only)
  behavioral?: number // omitted if null
}

// Build Recharts data from ranking payload without turning omitted signals into 0.
function toChartRows(rows: RankingRowOut[]): ChartRow[] {
  return rows.map((row) => {
    const item: ChartRow = {
      name: shortEmail(row.candidate_email), // X axis
      composite: row.composite_score ?? 0, // API already requires composite_score IS NOT NULL
    }
    if (row.resume_score !== null) {
      item.resume = row.resume_score // keep real zeros if ATS was 0
    }
    if (row.technical_score !== null) {
      item.technical = row.technical_score
    }
    if (row.communication_score !== null) {
      item.communication = row.communication_score
    }
    if (row.behavioral_score !== null) {
      item.behavioral = row.behavioral_score
    }
    return item
  })
}

// Recruiter score-distribution: composite bars + grouped signals from stored ranking rows.
export function ScoreDistributionChart({ rows }: { rows: RankingRowOut[] }) {
  const data = toChartRows(rows) // client-side projection only
  return (
    <Card data-testid="recruiter-score-chart">
      <CardHeader>
        <CardTitle>Score distribution</CardTitle>
        <CardDescription>
          Stored composites and signals from GET /scores/rankings. Omitted communication is not drawn as 0.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No scored sessions on this posting yet.</p>
        ) : (
          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                <Bar dataKey="composite" name="Composite" fill="var(--chart-1)" isAnimationActive={false} />
                <Bar dataKey="resume" name={SIGNAL_LABELS.resume} fill="var(--chart-2)" isAnimationActive={false} />
                <Bar dataKey="technical" name={SIGNAL_LABELS.technical} fill="var(--chart-3)" isAnimationActive={false} />
                <Bar
                  dataKey="communication"
                  name={SIGNAL_LABELS.communication}
                  fill="var(--chart-4)"
                  isAnimationActive={false}
                />
                <Bar dataKey="behavioral" name={SIGNAL_LABELS.behavioral} fill="var(--chart-5)" isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
