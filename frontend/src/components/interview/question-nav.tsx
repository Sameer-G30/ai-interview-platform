import type { AnswerOut } from "@/api/types" // one question row; navigation is by question_order
import { Button } from "@/components/ui/button" // Prev/Next; do not restyle the primitive

// Previous / next through answers in question_order. Follow-ups appear at the end after evaluate succeeds.
export function QuestionNav({
  answers, // current session answers, including any follow-up appended after a weak score
  index, // 0-based index into answers
  onIndex, // parent owns the selected question so submit/evaluate can stay on the same row
}: {
  answers: AnswerOut[] // ordered by question_order from GET /interviews/{id}
  index: number // currently displayed question
  onIndex: (next: number) => void // called by Prev/Next
}) {
  const total = answers.length // may grow by one after a score <= 2
  const current = answers[index] // undefined only if the list is empty (generate not done)
  const atStart = index <= 0 // disable Prev on the first question
  const atEnd = index >= total - 1 // disable Next on the last question (including a new follow-up)
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <p className="text-sm text-muted-foreground">
        Question {index + 1} of {total}
        {current?.is_follow_up === true ? " · follow-up" : ""}
        {current?.question_kind ? ` · ${current.question_kind}` : ""}
      </p>
      <div className="flex gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={atStart}
          data-testid="prev-question"
          onClick={() => {
            onIndex(Math.max(0, index - 1)) // stay in range
          }}
        >
          Previous
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={atEnd}
          data-testid="next-question"
          onClick={() => {
            onIndex(Math.min(total - 1, index + 1)) // stay in range; follow-up is just another index
          }}
        >
          Next
        </Button>
      </div>
    </div>
  )
}
