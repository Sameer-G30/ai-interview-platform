// Typed wrapper around the Phase 7 `GET /matches` endpoint. Auth is on by default (apiFetch).

import { apiFetch } from "@/api/client" // typed fetch with the single-flight refresh interceptor
import type { MatchListOut } from "@/api/types" // FastAPI JSON contract for the ranked-postings response

// GET /matches — candidate-only ranked postings. Omitting resumeId uses the caller's latest parsed resume.
export async function fetchMatches(resumeId?: string): Promise<MatchListOut> {
  const query = resumeId ? `?resume_id=${encodeURIComponent(resumeId)}` : "" // implicit-latest-resume lookup when absent
  return apiFetch<MatchListOut>(`/matches${query}`, {
    method: "GET", // FastAPI ranking read is GET
    auth: true, // owner is taken from the access JWT
  })
}

// Query-key factory so the Matches page and a future invalidateQueries share the same cache entries.
export const matchQueryKeys = {
  all: ["matches"] as const, // prefix for every matches query
  forResume: (resumeId?: string) => ["matches", resumeId ?? "latest"] as const, // GET /matches[?resume_id=]
}
