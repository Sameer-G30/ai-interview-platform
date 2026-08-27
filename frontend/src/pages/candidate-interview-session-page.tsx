import { useEffect, useState } from "react" // question index + text draft; sync when the session refetches
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query" // GET session + text submit
import { Link, useParams, useSearchParams } from "react-router-dom" // session id from the path; generate/eval jobs from ?job= / ?eval=

import { fetchInterview, interviewQueryKeys, submitAnswer } from "@/api/interviews" // GET session + POST text
import { ApiError } from "@/api/types" // poll / GET / submit failures
import type { AnswerOut, InterviewSessionOut } from "@/api/types" // question rows + session status
import { AudioRecorder } from "@/components/interview/audio-recorder" // MediaRecorder capture + upload
import { EvaluationCard } from "@/components/interview/evaluation-card" // score 0–5 + rationale
import { InterviewJobStatus } from "@/components/interview/interview-job-status" // queued/running/failed copy
import { QuestionNav } from "@/components/interview/question-nav" // previous / next by question_order
import { Button } from "@/components/ui/button" // submit + back links
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // page chrome
import { Skeleton } from "@/components/ui/skeleton" // pending generate placeholder
import { Textarea } from "@/components/ui/textarea" // text answer; judge needs answer_text
import { useJobStatus } from "@/hooks/use-job-status" // existing poller; do not write a second one

// First unanswered row, or the last row if every question already has text (completed / viewing history).
function firstUnansweredIndex(answers: AnswerOut[]): number {
  const open = answers.findIndex((row) => row.answer_text === null) // follow-ups are just later rows
  if (open === -1) {
    return Math.max(0, answers.length - 1) // stay on the last question when the session is complete
  }
  return open // generate just finished, or a follow-up was appended
}

// Candidate session screen: poll generate, then GET /interviews/{id}; submit text; poll evaluate; show follow-ups.
export function CandidateInterviewSessionPage() {
  const queryClient = useQueryClient() // refetch the session after evaluate succeeds (follow-up may appear)
  const { sessionId } = useParams() // /candidate/interview/:sessionId
  const [params, setParams] = useSearchParams() // ?job=<generate> from start; ?eval=<evaluate> after submit
  const generateJobId = params.get("job") // null if the user opened the session URL without a job query
  const evaluateJobId = params.get("eval") // null until a text submit returns async_job_id
  const generateQuery = useJobStatus(generateJobId) // disabled when generateJobId is null
  const evaluateQuery = useJobStatus(evaluateJobId) // disabled when evaluateJobId is null
  const generateStatus = generateQuery.data?.status // queued | running | succeeded | failed | undefined
  const evaluateStatus = evaluateQuery.data?.status // same union for the evaluate job
  const generateTerminal = generateStatus === "succeeded" || generateStatus === "failed" // stop waiting on generate
  const evaluateTerminal = evaluateStatus === "succeeded" || evaluateStatus === "failed" // then refetch the session
  const canFetchSession = sessionId !== undefined && (generateJobId === null || generateTerminal) // do not loop GET /interviews while queued

  const [index, setIndex] = useState(0) // selected answers[] slot; follow-ups append at the end
  const [draft, setDraft] = useState("") // textarea; not sent until Submit
  const [submitError, setSubmitError] = useState<string | null>(null) // 409 already-submitted / completed, or network
  const [indexReady, setIndexReady] = useState(false) // first unanswered pick runs once per session load
  const [pendingAnswerId, setPendingAnswerId] = useState<string | null>(null) // answer we just submitted, before GET refetch

  const sessionQuery = useQuery({
    queryKey: sessionId === undefined ? interviewQueryKeys.all : interviewQueryKeys.detail(sessionId), // idle key unused
    queryFn: () => fetchInterview(sessionId as string), // enabled-gate guarantees sessionId is set
    enabled: canFetchSession, // do not GET /interviews until generate succeeded/failed (or there is no job id)
    staleTime: 0, // results must not look fresh while we just transitioned from running
  })

  const session: InterviewSessionOut | undefined = sessionQuery.data // undefined until the first GET
  const answers = session?.answers ?? [] // empty while scheduled / generate failed
  const current = answers[index] // undefined if generate produced no rows (abandoned)

  useEffect(() => {
    if (session === undefined || session.answers.length === 0 || indexReady) {
      return // wait for questions, and do not override Prev/Next after the first pick
    }
    setIndex(firstUnansweredIndex(session.answers)) // land on the first open question
    setIndexReady(true) // subsequent refetches (evaluate) keep the current index
  }, [session, indexReady])

  useEffect(() => {
    if (current === undefined) {
      setDraft("") // no question yet
      return // nothing to hydrate
    }
    setDraft(current.answer_text ?? "") // submitted text is read-only; unanswered starts empty
  }, [current]) // switch question or a refetch that now has answer_text

  useEffect(() => {
    if (evaluateJobId === null || !evaluateTerminal || sessionId === undefined) {
      return // still polling, or no evaluate job in the URL
    }
    void queryClient.invalidateQueries({ queryKey: interviewQueryKeys.detail(sessionId) }) // score + maybe follow-up
  }, [evaluateJobId, evaluateTerminal, queryClient, sessionId])

  const generatePollError =
    generateQuery.error instanceof ApiError
      ? generateQuery.error.detail
      : generateQuery.isError
        ? generateQuery.error.message
        : null // poller error copy
  const evaluatePollError =
    evaluateQuery.error instanceof ApiError
      ? evaluateQuery.error.detail
      : evaluateQuery.isError
        ? evaluateQuery.error.message
        : null // evaluate poller error copy
  const sessionError =
    sessionQuery.error instanceof ApiError
      ? sessionQuery.error.detail
      : sessionQuery.isError
        ? sessionQuery.error.message
        : null // GET /interviews error copy

  const submit = useMutation({
    mutationFn: (text: string) => submitAnswer(sessionId as string, current?.id as string, text),
    onSuccess: (body) => {
      setSubmitError(null) // clear a previous 409
      setPendingAnswerId(body.answer_id) // freeze this row even before GET session returns answer_text
      const next = new URLSearchParams(params) // keep ?job= generate id
      next.set("eval", body.async_job_id) // poll this evaluate job with the same useJobStatus hook
      setParams(next, { replace: true }) // refresh-safe; do not add a history entry per submit
      void queryClient.invalidateQueries({
        queryKey: sessionId === undefined ? interviewQueryKeys.all : interviewQueryKeys.detail(sessionId),
      }) // answer_text is now set; disable the textarea immediately
    },
    onError: (caught) => {
      if (caught instanceof ApiError) {
        setSubmitError(caught.detail) // 409 already submitted / session completed / abandoned
        return // stay on this question
      }
      setSubmitError("could not submit — is the API running?") // network
    },
  })

  const thisAnswerPending = current !== undefined && current.id === pendingAnswerId // just submitted this row
  const alreadyAnswered = current !== undefined && (current.answer_text !== null || thisAnswerPending) // 409 if we POST again
  const sessionClosed = session?.status === "completed" || session?.status === "abandoned" // 409 on submit
  const thisAnswerEvaluating =
    evaluateJobId !== null &&
    !evaluateTerminal &&
    current !== undefined &&
    alreadyAnswered &&
    current.evaluation === null // do not show Q1's poller on Q2
  const canSubmit =
    current !== undefined &&
    draft.trim().length > 0 &&
    !alreadyAnswered &&
    !sessionClosed &&
    !submit.isPending &&
    !thisAnswerEvaluating

  if (sessionId === undefined) {
    return (
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
        <p className="text-sm text-destructive" role="alert">
          Missing session id.
        </p>
        <Button type="button" variant="outline" asChild>
          <Link to="/candidate/interview">Start an interview</Link>
        </Button>
      </div>
    )
  }

  const waitingOnGenerate =
    generateStatus === "queued" ||
    generateStatus === "running" ||
    (generateQuery.isPending && generateJobId !== null && !generateTerminal)

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold">Interview session</h1>
        <p className="text-muted-foreground">
          Generate and evaluate jobs poll GET /jobs/{"{id}"}. Questions come from GET /interviews/{"{id}"} after generate
          finishes. A follow-up may appear after a score of 0–2.
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Generate job</CardTitle>
          <CardDescription>
            {generateJobId !== null
              ? `Polling ${generateJobId}`
              : "No generate job id in the URL — reading the session row directly."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {generateJobId !== null ? (
            <InterviewJobStatus
              kind="generate"
              job={generateQuery.data}
              isLoading={generateQuery.isPending}
              pollError={generatePollError}
            />
          ) : (
            <p className="text-sm text-muted-foreground">Skipped generate polling because ?job= is missing.</p>
          )}
        </CardContent>
      </Card>
      {waitingOnGenerate ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <p className="text-sm text-muted-foreground">Waiting for questions…</p>
        </div>
      ) : null}
      {canFetchSession && sessionQuery.isPending ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-32 w-full" />
          <p className="text-sm text-muted-foreground">Loading session…</p>
        </div>
      ) : null}
      {sessionError !== null ? (
        <p className="text-sm text-destructive" role="alert">
          Could not load session: {sessionError}
        </p>
      ) : null}
      {session?.status === "abandoned" ? (
        <Card>
          <CardHeader>
            <CardTitle>Session abandoned</CardTitle>
            <CardDescription>
              Question generation failed. This session cannot accept answers. Start a new interview from Interview or
              Matches.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : null}
      {session?.status === "completed" ? (
        <p className="text-sm text-muted-foreground" data-testid="session-completed">
          This session is complete. You can still move through questions to read scores. Audio can still be uploaded for
          later transcription.
        </p>
      ) : null}
      {session !== undefined && session.status !== "abandoned" && answers.length > 0 && current !== undefined ? (
        <Card>
          <CardHeader>
            <CardTitle>Question</CardTitle>
            <CardDescription>{session.job_id ? "Posting-targeted interview" : "Practice interview"}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <QuestionNav answers={answers} index={index} onIndex={setIndex} />
            <p className="text-sm leading-relaxed" data-testid="question-text">
              {current.question_text}
            </p>
            <Textarea
              id="answer_text"
              data-testid="answer-text"
              rows={6}
              value={draft}
              disabled={alreadyAnswered || sessionClosed || submit.isPending || thisAnswerEvaluating}
              onChange={(event) => {
                setDraft(event.target.value) // local only until Submit
              }}
              placeholder="Type your answer. Recording is optional and is not scored this phase."
            />
            {submitError !== null ? (
              <p className="text-sm text-destructive" role="alert">
                {submitError}
              </p>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                disabled={!canSubmit}
                data-testid="submit-answer"
                onClick={() => {
                  setSubmitError(null) // clear a previous 409 before retrying
                  submit.mutate(draft.trim()) // POST { answer_text }; empty is blocked by canSubmit
                }}
              >
                {submit.isPending ? "Submitting…" : alreadyAnswered ? "Submitted" : "Submit answer"}
              </Button>
            </div>
            {evaluateJobId !== null && alreadyAnswered && current.evaluation === null ? (
              <InterviewJobStatus
                kind="evaluate"
                job={evaluateQuery.data}
                isLoading={evaluateQuery.isPending}
                pollError={evaluatePollError}
              />
            ) : null}
            {current.evaluation !== null ? <EvaluationCard evaluation={current.evaluation} /> : null}
            {current.is_follow_up === false &&
            current.evaluation !== null &&
            asNeedsFollowUpNotice(current.evaluation) &&
            answers.some((row) => row.is_follow_up && row.question_order > current.question_order) ? (
              <p className="text-sm text-muted-foreground">
                A follow-up was added at the end of the list (score 0–2). It is not the next original
                question — jump to the last item when you are ready. The list is not fixed at generate time.
              </p>
            ) : null}
            <AudioRecorder
              key={current.id} // remount per question so a leftover MediaRecorder cannot leak across rows
              sessionId={sessionId}
              answerId={current.id}
              hasAudio={current.has_audio}
              onUploaded={() => {
                void queryClient.invalidateQueries({ queryKey: interviewQueryKeys.detail(sessionId) }) // has_audio
              }}
            />
          </CardContent>
        </Card>
      ) : null}
      {session !== undefined && session.status !== "abandoned" && answers.length === 0 && !waitingOnGenerate ? (
        <p className="text-sm text-muted-foreground">No questions on this session yet.</p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant="outline" asChild>
          <Link to="/candidate/interview">New interview</Link>
        </Button>
        <Button type="button" variant="outline" asChild>
          <Link to="/candidate">Back to overview</Link>
        </Button>
      </div>
    </div>
  )
}

// True when the judge score is 0–2 (the same predicate as should_follow_up, ignoring is_follow_up).
function asNeedsFollowUpNotice(evaluation: unknown): boolean {
  if (typeof evaluation !== "object" || evaluation === null || !("score" in evaluation)) {
    return false // no score yet
  }
  const score = (evaluation as { score: unknown }).score // JSON number
  return typeof score === "number" && score <= 2 // follow-up rule; improvements alone do not count
}
