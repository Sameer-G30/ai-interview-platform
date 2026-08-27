import type { AnswerEvaluationOut } from "@/api/types" // judge JSON written to answers.evaluation

// Narrows an unknown GET /interviews evaluation field into AnswerEvaluationOut; missing keys become safe defaults.
export function asAnswerEvaluation(raw: unknown): AnswerEvaluationOut | null {
  if (typeof raw !== "object" || raw === null) {
    return null // backend stores null until interview_evaluate succeeds
  }
  const record = raw as Record<string, unknown> // FastAPI JSON object
  const scoreRaw = record.score // expected int 0–5
  const score = typeof scoreRaw === "number" && Number.isFinite(scoreRaw) ? scoreRaw : 0 // 0 if the worker omitted it
  const rationale = typeof record.rationale === "string" ? record.rationale : "" // empty rather than crashing the card
  const strengthsRaw = record.strengths // expected list[str]
  const strengths = Array.isArray(strengthsRaw)
    ? strengthsRaw.filter((item): item is string => typeof item === "string") // ignore unexpected entries
    : [] // missing list -> empty so the empty-state copy can render
  const improvementsRaw = record.improvements // expected list[str]
  const improvements = Array.isArray(improvementsRaw)
    ? improvementsRaw.filter((item): item is string => typeof item === "string") // ignore unexpected entries
    : [] // coaching notes; a non-empty list does not mean a follow-up was appended
  return { score, rationale, strengths, improvements } // UI-ready judge payload
}
