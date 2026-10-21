// Typed wrapper for polling a background job. Auth is on by default (apiFetch).

import { apiFetch } from "@/api/client" // typed fetch with the single-flight refresh interceptor
import type { AsyncJobOut } from "@/api/types" // FastAPI JSON contract for a job status poll

// GET /jobs/{id} — owner-only status poll; 404 for missing or someone else's job.
export async function fetchJob(jobId: string): Promise<AsyncJobOut> {
  return apiFetch<AsyncJobOut>(`/jobs/${jobId}`, {
    method: "GET", // FastAPI poll is GET
    auth: true, // interceptor will rotate the opaque refresh token on 401
  })
}

// Query-key factory so the poller and a future invalidateQueries share the same cache entries.
export const jobQueryKeys = {
  all: ["jobs"] as const, // prefix for every job query
  detail: (jobId: string) => ["jobs", "detail", jobId] as const, // GET /jobs/{id}
}
