// Typed wrappers around Phase 15 `/admin/*` endpoints. Auth is on by default (apiFetch).

import { apiFetch } from "@/api/client" // typed fetch with the single-flight refresh interceptor
import type {
  AdminPostingOut, // GET /admin/postings row
  AdminScoreListItemOut, // GET /admin/scores row
  AdminSessionListItemOut, // GET /admin/sessions row
  AdminUserPatch, // PATCH /admin/users/{id} body
  InterviewSessionStatus, // optional session list filter
  UpdatePostingRequest, // PATCH is_active only
  UserOut, // GET /admin/users row (same shape as GET /auth/me)
  UserRole, // optional user list filter
} from "@/api/types" // FastAPI JSON contracts; field names are snake_case

// Optional filters for GET /admin/users.
export type AdminUserListParams = {
  role?: UserRole // candidate | recruiter; omit for both
  is_active?: boolean // omit for active and deactivated
}

// Optional filters for GET /admin/postings.
export type AdminPostingListParams = {
  recruiter_id?: string // one owner's jobs
  is_active?: boolean // omit for active and inactive
}

// Optional filters for GET /admin/sessions.
export type AdminSessionListParams = {
  status?: InterviewSessionStatus // query alias `status` on the API
  user_id?: string // one candidate's history
}

// Build a query string from defined snake_case params (skip undefined).
function queryString(params: Record<string, string | boolean | undefined>): string {
  const search = new URLSearchParams() // browser query encoder
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) {
      continue // omit unused filters
    }
    search.set(key, String(value)) // bool becomes "true" / "false"; FastAPI parses that
  }
  const encoded = search.toString() // empty when nothing was set
  return encoded === "" ? "" : `?${encoded}` // leading ? only when needed
}

// GET /admin/users — admin-only list, newest created_at first.
export async function listAdminUsers(params: AdminUserListParams = {}): Promise<UserOut[]> {
  return apiFetch<UserOut[]>(`/admin/users${queryString(params)}`, {
    method: "GET", // FastAPI collection read is GET
    auth: true, // require_admin; interceptor rotates the opaque refresh token on 401
  })
}

// PATCH /admin/users/{id} — soft-disable via is_active; is_admin on recruiters only.
export async function patchAdminUser(userId: string, body: AdminUserPatch): Promise<UserOut> {
  return apiFetch<UserOut>(`/admin/users/${userId}`, {
    method: "PATCH", // FastAPI update is PATCH
    body, // { is_active? , is_admin? }; empty body is 422
    auth: true, // require_admin
  })
}

// GET /admin/postings — every recruiter's jobs. Do not use GET /postings for this (own-only).
export async function listAdminPostings(params: AdminPostingListParams = {}): Promise<AdminPostingOut[]> {
  return apiFetch<AdminPostingOut[]>(`/admin/postings${queryString(params)}`, {
    method: "GET", // FastAPI collection read is GET
    auth: true, // require_admin
  })
}

// PATCH /admin/postings/{id} — is_active only; no hard delete. Same body as owner PATCH /postings/{id}.
export async function patchAdminPosting(postingId: string, body: UpdatePostingRequest): Promise<AdminPostingOut> {
  return apiFetch<AdminPostingOut>(`/admin/postings/${postingId}`, {
    method: "PATCH", // FastAPI update is PATCH
    body, // { is_active }
    auth: true, // require_admin; 404 for an unknown posting UUID
  })
}

// GET /admin/sessions — every candidate including practice. Not GET /interviews (caller history).
export async function listAdminSessions(params: AdminSessionListParams = {}): Promise<AdminSessionListItemOut[]> {
  return apiFetch<AdminSessionListItemOut[]>(`/admin/sessions${queryString(params)}`, {
    method: "GET", // FastAPI collection read is GET
    auth: true, // require_admin
  })
}

// GET /admin/scores — stored Score rows with a composite, practice included. Does not recompute.
export async function listAdminScores(): Promise<AdminScoreListItemOut[]> {
  return apiFetch<AdminScoreListItemOut[]>("/admin/scores", {
    method: "GET", // FastAPI collection read is GET
    auth: true, // require_admin
  })
}

// Query-key factory so admin pages and invalidateQueries share the same cache entries.
export const adminQueryKeys = {
  all: ["admin"] as const, // prefix for every admin query
  users: (params: AdminUserListParams = {}) => ["admin", "users", params] as const, // GET /admin/users
  postings: (params: AdminPostingListParams = {}) => ["admin", "postings", params] as const, // GET /admin/postings
  sessions: (params: AdminSessionListParams = {}) => ["admin", "sessions", params] as const, // GET /admin/sessions
  scores: () => ["admin", "scores"] as const, // GET /admin/scores
}
