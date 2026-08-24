// Typed wrappers around Phase 4 `/jobs/*` endpoints. Auth is on by default (apiFetch).

import { apiFetch } from "@/api/client" // typed fetch with the single-flight refresh interceptor
import type { AsyncJobOut, DemoJobRequest } from "@/api/types" // FastAPI JSON contracts for enqueue/poll

// POST /jobs/demo — throwaway echo (or fail) job so the queue is testable without ml/.
export async function enqueueDemoJob(body: DemoJobRequest = {}): Promise<AsyncJobOut> {
  return apiFetch<AsyncJobOut>("/jobs/demo", {
    method: "POST", // FastAPI demo enqueue is POST
    body, // message / sleep_ms / fail; all optional with backend defaults
    auth: true, // owner is taken from the access JWT
  })
}

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
