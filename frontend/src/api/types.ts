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

