// Shared TypeScript types that mirror the FastAPI `/auth/*` JSON contracts from Phase 2.

// Product role stored on User.role; admin is NOT a third value here (it is `is_admin` on recruiter).
export type UserRole = "candidate" | "recruiter" // the only two values POST /auth/register accepts

// In-memory / localStorage shape of the token pair the interceptor and AuthProvider share.
export type AuthTokens = {
  accessToken: string // short-lived JWT sent as `Authorization: Bearer ...` on authenticated calls
  refreshToken: string // opaque random secret (NOT a JWT) posted to POST /auth/refresh
}

// Exact JSON body FastAPI returns from register/login/refresh (`TokenPairResponse`).
export type TokenPairResponse = {
  access_token: string // JWT access token; maps to AuthTokens.accessToken
  refresh_token: string // opaque refresh token; maps to AuthTokens.refreshToken
  token_type: string // always "bearer" from the backend; unused by the client beyond documentation
}

// Exact JSON body FastAPI returns from GET /auth/me (`UserOut`).
export type UserOut = {
  id: string // UUID string of the authenticated user
  email: string // normalized lowercase email
  full_name: string | null // optional display name; backend allows null
  role: UserRole // "candidate" or "recruiter" — never "admin"
  is_admin: boolean // extra capability flag; only meaningful when role is recruiter
  is_active: boolean // false means the account is suspended; login/refresh/me already reject these
}

// Frontend-facing user object with camelCase fields used by React components.
export type CurrentUser = {
  id: string // same UUID as UserOut.id
  email: string // same email as UserOut.email
  fullName: string | null // mapped from full_name
  role: UserRole // mapped from role
  isAdmin: boolean // mapped from is_admin; used only to show extra nav, not a third role
  isActive: boolean // mapped from is_active
}

// Body for POST /auth/register; `is_admin` is intentionally absent (ops-only later).
export type RegisterRequest = {
  email: string // candidate or recruiter email
  password: string // 8–128 characters, matching the backend Field constraints
  full_name?: string | null // optional display name
  role: UserRole // "candidate" (default on the backend) or "recruiter"
}

// Body for POST /auth/login.
export type LoginRequest = {
  email: string // account email
  password: string // plaintext password; never logged
}

// Job lifecycle stored on async_jobs.status; JSON is the enum value, not the member name.
export type AsyncJobStatus = "queued" | "running" | "succeeded" | "failed" // GET /jobs/{id} status field

// Exact JSON body FastAPI returns from POST /jobs/demo and GET /jobs/{id} (`AsyncJobOut`).
export type AsyncJobOut = {
  id: string // UUID string of the async_jobs row; poll this via GET /jobs/{id}
  job_type: string // e.g. "demo_echo"; later resume_parse / transcribe / evaluate
  status: AsyncJobStatus // queued while waiting, running while the worker is busy, then terminal
  user_id: string | null // owner; GET returns 404 for another user's id
  payload: Record<string, unknown> | null // input the worker received
  result: Record<string, unknown> | null // output once succeeded; null otherwise
  error: string | null // short failure summary once failed; null otherwise
  created_at: string // ISO timestamp of row insert
  updated_at: string // ISO timestamp of last status write
}

// Body for POST /jobs/demo; all fields optional because the backend supplies defaults.
export type DemoJobRequest = {
  message?: string // echoed in result.echo on success
  sleep_ms?: number // 0–5000; SPA demo uses a short delay so queued/running is visible
  fail?: boolean // tests only; the SPA demo never sends true
}

// Lifecycle stored on resumes.status; JSON is the enum value, not the member name.
export type ResumeStatus = "uploaded" | "processing" | "parsed" | "failed" // GET /resumes/{id} status field

// Per-signal ATS attribution stored under parsed_data.ats_breakdown once parsing succeeds.
export type AtsBreakdown = {
  section_points: number // points awarded for expected section headers being present
  contact_points: number // points awarded for email and/or phone being found
  skill_points: number // points awarded for ESCO PhraseMatcher hits
  length_points: number // points awarded for a healthy word count
  total: number // sum of the four signals, already clamped to [0, 100]
}

// JSON object written to resumes.parsed_data by ml.resume.run_resume_pipeline.
export type ParsedResumeData = {
  sections: Record<string, string> // section name -> extracted body text
  skills: string[] // de-duplicated ESCO preferred labels
  email: string | null // first email regex hit, if any
  phone: string | null // first phone regex hit, if any
  extractor_used: string // "pymupdf" or "pypdfium2"
  ats_breakdown: AtsBreakdown // explainable per-signal score
  word_count: number // whitespace-split token count of the raw extract
}

// Exact JSON body FastAPI returns from POST /resumes (`ResumeUploadOut`).
export type ResumeUploadOut = {
  resume_id: string // UUID string; poll results via GET /resumes/{resume_id}
  async_job_id: string // UUID string; poll parse progress via GET /jobs/{async_job_id}
  status: ResumeStatus // "uploaded" at this point; the worker advances it
}

// Exact JSON body FastAPI returns from GET /resumes/{id} (`ResumeOut`).
export type ResumeOut = {
  id: string // UUID string of the resumes row
  original_filename: string // candidate's filename, for display
  status: ResumeStatus // uploaded | processing | parsed | failed
  parsed_data: ParsedResumeData | null // sections/skills/contact once status == parsed
  ats_score: number | null // 0–100 once status == parsed; null otherwise
  created_at: string // ISO timestamp of row insert
  updated_at: string // ISO timestamp of last status write
}

// Body for POST /postings; required_skills stays one freeform textarea string, matching the backend.
export type CreatePostingRequest = {
  title: string // 1–200 chars, matches Job.title's column length
  description: string // free text; Job.description is an unbounded Text column
  required_skills?: string | null // comma/line separated; optional
  is_active?: boolean // defaults true server-side if omitted
}

// Body for PATCH /postings/{id}; only is_active is mutable, no hard delete exists.
export type UpdatePostingRequest = {
  is_active: boolean
}

// Exact JSON body FastAPI returns for one posting (`PostingOut`), from POST/GET/PATCH /postings*.
export type PostingOut = {
  id: string // UUID string of the jobs row
  title: string
  description: string
  required_skills: string | null
  is_active: boolean
  has_embedding: boolean // true once the posting_embed worker has written Job.embedding
  created_at: string // ISO timestamp of row insert
  updated_at: string // ISO timestamp of last update
}

// Exact JSON body FastAPI returns from POST /postings (`PostingCreateOut`).
export type PostingCreateOut = {
  posting: PostingOut
  async_job_id: string // poll embedding progress via the existing GET /jobs/{async_job_id}
}

// One ranked posting from GET /matches (`MatchOut`).
export type MatchOut = {
  posting_id: string // UUID string of the jobs row
  title: string
  score: number // SBERT cosine similarity, practically in [0, 1]
  matched_skills: string[] // required skills the resume already has (sorted ESCO preferred labels)
  missing_skills: string[] // required skills the resume is missing (sorted ESCO preferred labels)
}

// Exact JSON body FastAPI returns from GET /matches (`MatchListOut`).
export type MatchListOut = {
  resume_id: string // the parsed resume this ranking was computed against
  matches: MatchOut[] // sorted by score descending
}

// Session lifecycle stored on interview_sessions.status; JSON is the enum value, not the member name.
export type InterviewSessionStatus = "scheduled" | "in_progress" | "completed" | "abandoned"

// Judge payload stored on answers.evaluation once interview_evaluate succeeds (Phase 8 AnswerEvaluation).
export type AnswerEvaluationOut = {
  score: number // integer 0–5; the follow-up predicate is score <= 2
  rationale: string // short justification from the judge
  strengths: string[] // what went well
  improvements: string[] // coaching notes; non-empty does NOT spawn a follow-up
}

// One answers row from GET /interviews/{id} (`AnswerOut`). JSON names match the live API (snake_case).
export type AnswerOut = {
  id: string // UUID string; submit target POST /interviews/{session_id}/answers/{id}
  question_order: number // 0-based ask order, including follow-ups appended at the end
  question_text: string // generated (or follow-up) prompt
  question_kind: string // "technical" | "behavioral"
  is_follow_up: boolean // True when the evaluate worker appended this row
  answer_text: string | null // NULL until the candidate submits text
  evaluation: AnswerEvaluationOut | null // {score, rationale, strengths, improvements} once judged
  has_audio: boolean // True once POST .../audio wrote answers.audio_path (path itself is not in JSON)
  created_at: string // ISO timestamp of row insert
  updated_at: string // ISO timestamp of last write
}

// Exact JSON body FastAPI returns from GET /interviews/{id} (`InterviewSessionOut`).
export type InterviewSessionOut = {
  id: string // UUID string of the interview_sessions row
  resume_id: string // parsed resume this session was generated from
  job_id: string | null // optional posting; null for a practice interview
  status: InterviewSessionStatus // scheduled | in_progress | completed | abandoned
  started_at: string | null // set when generated questions are persisted
  completed_at: string | null // set when every current question is answered and no follow-up is added
  answers: AnswerOut[] // ordered by question_order
  created_at: string // ISO timestamp of row insert
  updated_at: string // ISO timestamp of last update
}

// Body for POST /interviews; both ids optional. Omitted resume_id uses the latest parsed resume.
export type InterviewStartRequest = {
  resume_id?: string | null // must be owned + parsed when set; 404/409 same as GET /matches
  job_id?: string | null // optional posting; 404 if missing, 409 if inactive
}

// Exact JSON body FastAPI returns from POST /interviews (`InterviewStartOut`).
export type InterviewStartOut = {
  session_id: string // poll results via GET /interviews/{session_id}
  async_job_id: string // poll generate progress via the existing GET /jobs/{id}
  status: InterviewSessionStatus // "scheduled" at this point; the worker advances it to in_progress
}

// Body for POST /interviews/{session_id}/answers/{answer_id}. Text only; audio is a separate upload.
export type AnswerSubmitRequest = {
  answer_text: string // min_length 1 on the API; empty is 422
}

// Exact JSON body FastAPI returns from text submit (`AnswerSubmitOut`).
export type AnswerSubmitOut = {
  answer_id: string // the row whose evaluation the client will read after polling
  async_job_id: string // poll via GET /jobs/{id}; same useJobStatus hook as generate
  session_status: InterviewSessionStatus // still in_progress until the worker completes the session
}

// Exact JSON body FastAPI returns from POST .../audio (`AudioUploadOut`).
export type AudioUploadOut = {
  answer_id: string // the row whose audio_path was written
  has_audio: boolean // always true on success
}

export class ApiError extends Error {
  readonly status: number // HTTP status code from the failed response
  readonly detail: string // human-readable message parsed from FastAPI's `detail` field

  constructor(status: number, detail: string) {
    super(detail) // Error.message is the same string the UI can display
    this.name = "ApiError" // distinguishes this from generic TypeError/network failures
    this.status = status // stored so callers can branch on 401/409/422/429
    this.detail = detail // stored separately so UI code does not have to read .message
  }
}

