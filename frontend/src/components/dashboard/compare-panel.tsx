import type { ScoreOut } from "@/api/types" // GET /scores/compare sessions
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // chrome
import { SIGNAL_LABELS, SIGNAL_ORDER, formatSignalScore, signalValue } from "@/lib/dashboard" // omitted ≠ 0

// Side-by-side stored scores from GET /scores/compare. Browser does not re-aggregate.
export function ComparePanel({ scores }: { scores: ScoreOut[] }) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2" data-testid="recruiter-compare">
      {scores.map((score) => {
        const omitted = score.attribution?.omitted ?? [] // scoring_v1 list
        return (
          <Card key={score.session_id} size="sm">
            <CardHeader>
              <CardTitle className="font-mono text-sm">{score.session_id.slice(0, 8)}…</CardTitle>
              <CardDescription>Composite {formatSignalScore(score.composite_score)}</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {SIGNAL_ORDER.map((name) => (
                <div key={name} className="flex items-center justify-between gap-2 text-sm">
                  <span className="text-muted-foreground">{SIGNAL_LABELS[name]}</span>
                  <span className="tabular-nums">{formatSignalScore(signalValue(score, name))}</span>
                </div>
              ))}
              {omitted.length > 0 ? (
                <p className="text-xs text-muted-foreground">Omitted: {omitted.join(", ")}</p>
              ) : null}
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
