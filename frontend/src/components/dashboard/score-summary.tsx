import { Link } from "react-router-dom" // open the completed session that produced this Score

import type { ScoreOut } from "@/api/types" // GET /scores/{id} stored row
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // summary chrome
import { SIGNAL_LABELS, SIGNAL_ORDER, formatSignalScore, signalValue } from "@/lib/dashboard" // omitted ≠ 0

// Candidate score summary: composite + four signals + attribution omitted list from a stored Score.
export function ScoreSummaryCard({
  score,
  sessionPath,
}: {
  score: ScoreOut // GET /scores/{id}; never recomputed in the browser
  sessionPath: string // /candidate/interview/{id}
}) {
  const omitted = score.attribution?.omitted ?? [] // scoring_v1 omitted names
  return (
    <Card data-testid="candidate-score-summary">
      <CardHeader>
        <CardTitle>Score summary</CardTitle>
        <CardDescription>
          Stored composite after renormalize (coding dropped). Missing signals are omitted, not zero.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-3xl font-semibold tabular-nums">
          {formatSignalScore(score.composite_score)}
          <span className="ml-2 text-sm font-normal text-muted-foreground">composite</span>
        </p>
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {SIGNAL_ORDER.map((name) => (
            <div key={name} className="rounded-lg border border-border p-3">
              <dt className="text-xs text-muted-foreground">{SIGNAL_LABELS[name]}</dt>
              <dd className="text-sm font-medium tabular-nums">{formatSignalScore(signalValue(score, name))}</dd>
            </div>
          ))}
        </dl>
        {omitted.length > 0 ? (
          <p className="text-sm text-muted-foreground">
            Omitted this session: {omitted.join(", ")}. Communication stays “Not recorded” on text-only interviews.
          </p>
        ) : null}
        <Link className="text-sm font-medium underline underline-offset-4" to={sessionPath}>
          Open this session
        </Link>
      </CardContent>
    </Card>
  )
}

// Empty copy when there is no stored Score yet (no sessions, or only in_progress / abandoned).
export function ScoreSummaryEmpty({
  title,
  body,
}: {
  title: string // short heading
  body: string // what to do next
}) {
  return (
    <Card data-testid="candidate-score-summary">
      <CardHeader>
        <CardTitle>Score summary</CardTitle>
        <CardDescription>{title}</CardDescription>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">{body}</p>
      </CardContent>
    </Card>
  )
}
