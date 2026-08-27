import { asAnswerEvaluation } from "@/lib/answer-evaluation" // defensive parse of answers.evaluation JSON

// Per-answer judge card: score 0–5, rationale, strengths, improvements. Follow-up is a separate answers row.
export function EvaluationCard({ evaluation }: { evaluation: unknown }) {
  const parsed = asAnswerEvaluation(evaluation) // null until interview_evaluate has written the JSON
  if (parsed === null) {
    return null // parent shows the evaluate-job poller instead
  }
  const clamped = Math.max(0, Math.min(5, parsed.score)) // bar width; schema already enforces 0–5
  const percent = (clamped / 5) * 100 // 0–100 for the score bar
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border p-3" data-testid="evaluation-card">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-sm font-medium">Score</p>
        <p className="text-sm tabular-nums" data-testid="evaluation-score">
          {clamped} / 5
        </p>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary" style={{ width: `${percent}%` }} />
      </div>
      {parsed.rationale.length > 0 ? (
        <p className="text-sm text-muted-foreground">{parsed.rationale}</p>
      ) : null}
      {parsed.strengths.length > 0 ? (
        <div className="flex flex-col gap-1">
          <p className="text-xs font-medium">Strengths</p>
          <ul className="list-inside list-disc text-sm text-muted-foreground">
            {parsed.strengths.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {parsed.improvements.length > 0 ? (
        <div className="flex flex-col gap-1">
          <p className="text-xs font-medium">Improvements</p>
          <ul className="list-inside list-disc text-sm text-muted-foreground">
            {parsed.improvements.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}
