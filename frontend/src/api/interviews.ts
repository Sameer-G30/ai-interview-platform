// Typed wrappers around Phase 9/10 `/interviews/*` endpoints. Auth is on by default.

import { apiFetch, apiUpload } from "@/api/client" // JSON POST/GET plus multipart audio via XHR
import type {
  AnswerSubmitOut,
  AudioUploadOut,
  InterviewSessionOut,
  InterviewStartOut,
  InterviewStartRequest,
} from "@/api/types" // FastAPI JSON contracts; field names are snake_case

export const MAX_AUDIO_BYTES = 10 * 1024 * 1024 // matches backend _MAX_AUDIO_BYTES (10 MiB)

export const AUDIO_MIME = "audio/webm;codecs=opus" // Chromium MediaRecorder target; do not promise Safari

// POST /interviews — candidate-only start. `{}` is a practice session from the latest parsed resume.
export async function startInterview(body: InterviewStartRequest = {}): Promise<InterviewStartOut> {
  return apiFetch<InterviewStartOut>("/interviews", {
    method: "POST", // FastAPI start is POST; 201 with session_id + async_job_id
    body, // resume_id / job_id optional; omit both for practice
    auth: true, // owner is taken from the access JWT
  })
}

// GET /interviews/{id} — owner-only session read; 404 for missing or someone else's session.
export async function fetchInterview(sessionId: string): Promise<InterviewSessionOut> {
  return apiFetch<InterviewSessionOut>(`/interviews/${sessionId}`, {
    method: "GET", // FastAPI session poll is GET
    auth: true, // interceptor will rotate the opaque refresh token on 401
  })
}

// POST /interviews/{session_id}/answers/{answer_id} — stores text and enqueues interview_evaluate.
export async function submitAnswer(sessionId: string, answerId: string, answerText: string): Promise<AnswerSubmitOut> {
  return apiFetch<AnswerSubmitOut>(`/interviews/${sessionId}/answers/${answerId}`, {
    method: "POST", // FastAPI text submit is POST
    body: { answer_text: answerText }, // snake_case matches AnswerSubmitIn; min_length 1
    auth: true, // candidate-only; recruiter is 403
  })
}

// POST /interviews/{session_id}/answers/{answer_id}/audio — multipart field `file`; does not enqueue evaluate.
export async function uploadAnswerAudio(
  sessionId: string, // parent session UUID
  answerId: string, // answers row UUID
  file: File, // WebM/Opus blob from MediaRecorder
  onProgress?: (percent: number) => void, // XHR upload progress; 100 does not mean Whisper ran
): Promise<AudioUploadOut> {
  const formData = new FormData() // multipart body; do not JSON.stringify (apiFetch would)
  formData.append("file", file, file.name || "answer.webm") // FastAPI UploadFile field is named `file`
  return apiUpload<AudioUploadOut>(`/interviews/${sessionId}/answers/${answerId}/audio`, formData, {
    auth: true, // owner is taken from the access JWT
    onProgress, // forwarded to XMLHttpRequest.upload.onprogress
  })
}

// Results URL: keep session_id in the path and the generate job id in ?job=, like resume results.
export function interviewSessionPath(sessionId: string, generateJobId: string): string {
  return `/candidate/interview/${sessionId}?job=${encodeURIComponent(generateJobId)}` // poll GET /jobs then GET session
}

// Query-key factory so the session page and invalidateQueries share the same cache entries.
export const interviewQueryKeys = {
  all: ["interviews"] as const, // prefix for every interview query
  detail: (sessionId: string) => ["interviews", "detail", sessionId] as const, // GET /interviews/{id}
}
