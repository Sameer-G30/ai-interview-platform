import { useEffect, useState } from "react" // selected question index, uploading flag, URL sync after transcribe
import { useQuery, useQueryClient } from "@tanstack/react-query" // GET session; refetch when a job finishes
import { Link, useParams, useSearchParams } from "react-router-dom" // session id from the path; ?job= generate, ?eval= evaluate

import { fetchInterview, interviewQueryKeys } from "@/api/interviews" // GET session
import { ApiError } from "@/api/types" // poll / GET failures
import type { AnswerOut, AudioUploadOut, InterviewSessionOut } from "@/api/types" // question rows + session status
import { AudioRecorder } from "@/components/interview/audio-recorder" // MediaRecorder capture + upload (required)
import { DownloadReportButton } from "@/components/interview/download-report" // WeasyPrint PDF for completed sessions
import { EvaluationCard } from "@/components/interview/evaluation-card" // score 0-5 + rationale
import { FluencyPanel } from "@/components/interview/fluency-panel" // both fluency arms + prosody
import { InterviewJobStatus } from "@/components/interview/interview-job-status" // queued/running/failed copy
import { QuestionNav } from "@/components/interview/question-nav" // previous / next by question_order
import { TranscriptViewer } from "@/components/interview/transcript-viewer" // transcript + word timings
import { PageHeader } from "@/components/layout/page-header" // shared title block
import { Button } from "@/components/ui/button" // links
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // page chrome
import { Skeleton } from "@/components/ui/skeleton" // pending generate placeholder
import { useJobStatus } from "@/hooks/use-job-status" // existing poller; do not write a second one
import { asSpeechMetrics, resolveSpeechAnalysisState } from "@/lib/speech-metrics" // defensive parse; no invented rates

// The four steps a spoken answer goes through, in order.
const STEPS = ["Recording", "Uploading", "Transcribing", "Scoring"] as const
type Step = (typeof STEPS)[number] | "Scored" // "Scored" means every step is done

// First row without an evaluation, or the last row when every question is scored (completed / history).
function firstOpenIndex(answers: AnswerOut[]): number {
  const open = answers.findIndex((row) => row.evaluation === null) // follow-ups are just later rows
  return open === -1 ? Math.max(0, answers.length - 1) : open
}

// Progress line: the active step is bold, finished steps are muted with a check, later steps are plain.
function ProgressSteps({ step }: { step: Step }) {
  const activeIndex = step === "Scored" ? STEPS.length : STEPS.indexOf(step) // all done when Scored
  return (
    <ol className="flex flex-wrap gap-x-4 gap-y-1 text-sm" aria-label="Answer progress" data-testid="progress-steps">
      {STEPS.map((name, position) => (
        <li
          key={name}
          aria-current={position === activeIndex ? "step" : undefined}
          className={
            position === activeIndex
              ? "font-semibold text-primary"
              : position < activeIndex
                ? "text-muted-foreground"
                : "text-muted-foreground/60"
          }
        >
          {position < activeIndex ? "\u2713 " : ""}
          {name}
        </li>
      ))}
    </ol>
  )
}

// Candidate session screen: questions come from the generate job; every answer is recorded, transcribed,
// shown back as "What we heard", then scored. There is no text box.
export function CandidateInterviewSessionPage() {
  const queryClient = useQueryClient() // refetch the session after a job finishes
  const { sessionId } = useParams() // /candidate/interview/:sessionId
  const [params, setParams] = useSearchParams() // ?job=<generate> from start; ?eval=<evaluate> after transcribe
  const generateJobId = params.get("job") // null if the URL has no generate job
  const evaluateJobId = params.get("eval") // null until a transcribe job reports its evaluate job
  const generateQuery = useJobStatus(generateJobId) // disabled when null
  const evaluateQuery = useJobStatus(evaluateJobId) // disabled when null
  const generateStatus = generateQuery.data?.status // queued | running | succeeded | failed | undefined
  const evaluateStatus = evaluateQuery.data?.status // same union
  const generateTerminal = generateStatus === "succeeded" || generateStatus === "failed"
  const evaluateTerminal = evaluateStatus === "succeeded" || evaluateStatus === "failed"
  const canFetchSession = sessionId !== undefined && (generateJobId === null || generateTerminal) // no loop while queued

  const [index, setIndex] = useState(0) // selected answers[] slot; follow-ups append at the end
  const [indexReady, setIndexReady] = useState(false) // the first open-question pick runs once per load
  const [uploading, setUploading] = useState(false) // the recorder is sending bytes
  const [transcribeJobs, setTranscribeJobs] = useState<Record<string, string>>({}) // answer_id -> job id, in memory

  const sessionQuery = useQuery({
    queryKey: sessionId === undefined ? interviewQueryKeys.all : interviewQueryKeys.detail(sessionId),
    queryFn: () => fetchInterview(sessionId as string), // enabled-gate guarantees sessionId is set
    enabled: canFetchSession, // do not GET the session until generate finished (or there is no job id)
    staleTime: 0, // results must not look fresh right after a job finishes
  })

  const session: InterviewSessionOut | undefined = sessionQuery.data // undefined until the first GET
  const answers = session?.answers ?? [] // empty while scheduled / generate failed
  const current = answers[index] // undefined if generate produced no rows
  const transcribeJobId = current !== undefined ? (transcribeJobs[current.id] ?? null) : null // per question
  const transcribeQuery = useJobStatus(transcribeJobId) // disabled when this question has no in-memory job
  const transcribeStatus = transcribeQuery.data?.status
  const transcribeTerminal = transcribeStatus === "succeeded" || transcribeStatus === "failed"
  const transcribeResult = transcribeQuery.data?.result ?? null // carries evaluate_async_job_id / evaluate_enqueued

  const speechMetrics = current !== undefined ? asSpeechMetrics(current.speech_metrics) : null // null until transcribe
  const speechState =
    current !== undefined
      ? resolveSpeechAnalysisState({
          hasAudio: current.has_audio,
          transcript: current.transcript,
          metrics: speechMetrics,
          transcribeJobId,
          transcribeStatus,
        })
      : "text-only" // no current row yet

  useEffect(() => {
    if (session === undefined || session.answers.length === 0 || indexReady) {
      return // wait for questions; do not override Previous/Next after the first pick
    }
    setIndex(firstOpenIndex(session.answers)) // land on the first unscored question
    setIndexReady(true)
  }, [session, indexReady])

  // After transcribe succeeds, follow its evaluate job id (kept in ?eval= so a refresh resumes polling).
  const nextEvaluateId =
    transcribeResult !== null && typeof transcribeResult.evaluate_async_job_id === "string"
      ? transcribeResult.evaluate_async_job_id
      : null
  useEffect(() => {
    if (nextEvaluateId === null || nextEvaluateId === evaluateJobId) {
      return // nothing to follow, or already following it
    }
    const next = new URLSearchParams(params) // keep ?job= generate id
    next.set("eval", nextEvaluateId)
    setParams(next, { replace: true }) // refresh-safe; no history entry per answer
  }, [nextEvaluateId, evaluateJobId, params, setParams])

  useEffect(() => {
    if (evaluateJobId === null || !evaluateTerminal || sessionId === undefined) {
      return
    }
    void queryClient.invalidateQueries({ queryKey: interviewQueryKeys.detail(sessionId) }) // score + maybe follow-up
  }, [evaluateJobId, evaluateTerminal, queryClient, sessionId])

  useEffect(() => {
    if (transcribeJobId === null || !transcribeTerminal || sessionId === undefined) {
      return
    }
    void queryClient.invalidateQueries({ queryKey: interviewQueryKeys.detail(sessionId) }) // transcript + metrics
  }, [transcribeJobId, transcribeTerminal, queryClient, sessionId])

  const pollError = (error: unknown): string | null =>
    error instanceof ApiError ? error.detail : error instanceof Error ? error.message : null // poller error copy
  const generatePollError = pollError(generateQuery.error)
  const evaluatePollError = pollError(evaluateQuery.error)
  const transcribePollError = pollError(transcribeQuery.error)
  const sessionError = pollError(sessionQuery.error)

  if (sessionId === undefined) {
    return (
      <div className="flex flex-col gap-4">
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

  const sessionClosed = session?.status === "completed" || session?.status === "abandoned"
  const scored = current !== undefined && current.evaluation !== null // this question is done
  const heardText = current?.answer_text ?? null // the transcript copy the judge reads
  const awaitingScore = current !== undefined && heardText !== null && !scored // transcript ready, judge pending
  const emptyTranscript =
    transcribeStatus === "succeeded" && transcribeResult !== null && transcribeResult.evaluate_enqueued === false
  const transcribeFailed = transcribeStatus === "failed"
  const evaluateFailed = awaitingScore && evaluateStatus === "failed"
  const transcribing = transcribeStatus === "queued" || transcribeStatus === "running"
  const step: Step = scored
    ? "Scored"
    : uploading
      ? "Uploading"
      : awaitingScore && !evaluateFailed
        ? "Scoring"
        : transcribing
          ? "Transcribing"
          : "Recording"

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <PageHeader
        title="Interview session"
        description="Answer each question aloud. We transcribe your speech, show you what we heard, and score it."
      />
      {generateJobId !== null && !generateTerminal ? (
        <InterviewJobStatus
          kind="generate"
          job={generateQuery.data}
          isLoading={generateQuery.isPending}
          pollError={generatePollError}
        />
      ) : null}
      {generateStatus === "failed" ? (
        <InterviewJobStatus kind="generate" job={generateQuery.data} isLoading={false} pollError={generatePollError} />
      ) : null}
      {waitingOnGenerate ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <p className="text-sm text-muted-foreground">Preparing your questions...</p>
        </div>
      ) : null}
      {canFetchSession && sessionQuery.isPending ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-32 w-full" />
          <p className="text-sm text-muted-foreground">Loading session...</p>
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
              Question generation failed, so this session cannot accept answers. Start a new interview from Interview
              or Matches.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : null}
      {session?.status === "completed" ? (
        <p className="text-sm text-muted-foreground" data-testid="session-completed">
          This session is complete. Move through the questions to review what we heard and how each answer scored.
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
            <ProgressSteps step={step} />
            {current.is_follow_up === false &&
            current.evaluation !== null &&
            asNeedsFollowUpNotice(current.evaluation) &&
            answers.some((row) => row.is_follow_up && row.question_order > current.question_order) ? (
              <p className="text-sm text-muted-foreground">
                A follow-up was added at the end of the list because this answer needs more detail. Jump to the last
                question when you are ready.
              </p>
            ) : null}
            {!scored && !sessionClosed ? (
              <p className="text-sm font-medium" data-testid="record-required">
                Recording is required to answer this question.
              </p>
            ) : null}
            <AudioRecorder
              key={current.id} // remount per question so a leftover MediaRecorder cannot leak across rows
              sessionId={sessionId}
              answerId={current.id}
              hasAudio={current.has_audio}
              disabled={scored || sessionClosed}
              onUploadingChange={setUploading}
              onUploaded={(body: AudioUploadOut) => {
                setTranscribeJobs((prev) => ({ ...prev, [body.answer_id]: body.async_job_id })) // reuse useJobStatus
                void queryClient.invalidateQueries({ queryKey: interviewQueryKeys.detail(sessionId) }) // has_audio
              }}
            />
            {transcribeJobId !== null && !scored ? (
              <InterviewJobStatus
                kind="transcribe"
                job={transcribeQuery.data}
                isLoading={transcribeQuery.isPending}
                pollError={transcribePollError}
              />
            ) : null}
            {emptyTranscript ? (
              <p className="text-sm text-destructive" role="alert" data-testid="empty-transcript">
                We could not hear anything in that recording. Please record this answer again.
              </p>
            ) : null}
            {transcribeFailed ? null : awaitingScore && evaluateJobId !== null ? (
              <InterviewJobStatus
                kind="evaluate"
                job={evaluateQuery.data}
                isLoading={evaluateQuery.isPending}
                pollError={evaluatePollError}
              />
            ) : null}
            {heardText !== null ? (
              <div className="flex flex-col gap-1 rounded-lg border border-border bg-muted/30 p-3">
                <p className="text-sm font-medium">What we heard</p>
                <p className="text-sm leading-relaxed" data-testid="answer-text">
                  {heardText}
                </p>
              </div>
            ) : null}
            {current.evaluation !== null ? <EvaluationCard evaluation={current.evaluation} /> : null}
            <TranscriptViewer transcript={current.transcript} metrics={speechMetrics} state={speechState} />
            <FluencyPanel metrics={speechMetrics} state={speechState} />
          </CardContent>
        </Card>
      ) : null}
      {session !== undefined && session.status !== "abandoned" && answers.length === 0 && !waitingOnGenerate ? (
        <p className="text-sm text-muted-foreground">No questions on this session yet.</p>
      ) : null}
      {session !== undefined && session.status === "completed" ? (
        <Card>
          <CardHeader>
            <CardTitle>Session report</CardTitle>
            <CardDescription>
              Your composite score combines your resume, technical answers, communication, and behavioral answers.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <DownloadReportButton sessionId={session.id} />
          </CardContent>
        </Card>
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

// True when the judge score is 0-2 (the same predicate as should_follow_up, ignoring is_follow_up).
function asNeedsFollowUpNotice(evaluation: unknown): boolean {
  if (typeof evaluation !== "object" || evaluation === null || !("score" in evaluation)) {
    return false // no score yet
  }
  const score = (evaluation as { score: unknown }).score // JSON number
  return typeof score === "number" && score <= 2 // follow-up rule; improvements alone do not count
}
