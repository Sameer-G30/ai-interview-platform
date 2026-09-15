// Typed wrappers around Phase 13 `/scores/*` and `/reports/{id}`. Auth is on by default.

import { apiBlob, apiFetch } from "@/api/client" // JSON GET plus binary PDF GET (not apiFetch — that JSON-parses)
import type { ComparisonOut, RankingOut, ScoreOut } from "@/api/types" // FastAPI JSON; snake_case field names

// GET /scores/{session_id} — candidate own session, or recruiter for a session on an owned posting.
export async function fetchScore(sessionId: string): Promise<ScoreOut> {
  return apiFetch<ScoreOut>(`/scores/${sessionId}`, {
    method: "GET", // FastAPI score read is GET; does not recompute
    auth: true, // interceptor rotates the opaque refresh token on 401
  })
}

// GET /reports/{session_id} — WeasyPrint PDF bytes. 404 for the wrong id; 503 if cairo is missing.
export async function downloadReportPdf(sessionId: string): Promise<Blob> {
  return apiBlob(`/reports/${sessionId}`, {
    method: "GET", // FastAPI streams application/pdf
    auth: true, // same owner-only 404 as GET /scores/{id}
  })
}

// GET /scores/rankings?posting_id= — recruiter-only completed scored sessions, composite desc.
export async function fetchScoreRankings(postingId: string): Promise<RankingOut> {
  const query = `?posting_id=${encodeURIComponent(postingId)}` // jobs.id the recruiter owns
  return apiFetch<RankingOut>(`/scores/rankings${query}`, {
    method: "GET", // FastAPI ranking read is GET; does not recompute
    auth: true, // interceptor rotates the opaque refresh token on 401
  })
}

// GET /scores/compare?session_ids=&session_ids= — recruiter-only; ≥2 distinct ids or 422.
export async function fetchScoreCompare(sessionIds: string[]): Promise<ComparisonOut> {
  const params = new URLSearchParams() // repeat the same key; FastAPI Query list
  for (const id of sessionIds) {
    params.append("session_ids", id) // do not JSON-stringify; this is a query string
  }
  return apiFetch<ComparisonOut>(`/scores/compare?${params.toString()}`, {
    method: "GET", // FastAPI compare read is GET; 404s the whole call if any id is foreign/practice
    auth: true, // candidates 403 via require_recruiter
  })
}

// Query-key factory so dashboards share cache entries with the session-page download.
export const scoreQueryKeys = {
  all: ["scores"] as const, // prefix
  detail: (sessionId: string) => ["scores", "detail", sessionId] as const, // GET /scores/{id}
  rankings: (postingId: string) => ["scores", "rankings", postingId] as const, // GET /scores/rankings
  compare: (sessionIds: string[]) => ["scores", "compare", ...sessionIds] as const, // GET /scores/compare
}
