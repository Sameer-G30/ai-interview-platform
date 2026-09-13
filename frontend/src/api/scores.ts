// Typed wrappers around Phase 13 `/scores/*` and `/reports/{id}`. Auth is on by default.

import { apiBlob, apiFetch } from "@/api/client" // JSON GET plus binary PDF GET (not apiFetch — that JSON-parses)
import type { ScoreOut } from "@/api/types" // FastAPI JSON; snake_case field names

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

// Query-key factory so a future dashboard can share cache entries with the session-page download.
export const scoreQueryKeys = {
  all: ["scores"] as const, // prefix
  detail: (sessionId: string) => ["scores", "detail", sessionId] as const, // GET /scores/{id}
}
