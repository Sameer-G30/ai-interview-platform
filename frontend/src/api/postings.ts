// Typed wrappers around Phase 7 `/postings/*` endpoints. Auth is on by default (apiFetch).

import { apiFetch } from "@/api/client" // typed fetch with the single-flight refresh interceptor
import type { CreatePostingRequest, PostingCreateOut, PostingOut, UpdatePostingRequest } from "@/api/types" // FastAPI JSON contracts

// POST /postings — recruiter-only create; enqueues posting_embed and returns both ids at once.
export async function createPosting(body: CreatePostingRequest): Promise<PostingCreateOut> {
  return apiFetch<PostingCreateOut>("/postings", {
    method: "POST", // FastAPI create is POST
    body, // title / description / required_skills / is_active
    auth: true, // owner is taken from the access JWT
  })
}

// GET /postings — recruiter-only list of the caller's own postings, newest first.
export async function listPostings(): Promise<PostingOut[]> {
  return apiFetch<PostingOut[]>("/postings", {
    method: "GET", // FastAPI list is GET
    auth: true, // interceptor will rotate the opaque refresh token on 401
  })
}

// PATCH /postings/{id} — recruiter-only, owner-only; only is_active is mutable.
export async function updatePosting(postingId: string, body: UpdatePostingRequest): Promise<PostingOut> {
  return apiFetch<PostingOut>(`/postings/${postingId}`, {
    method: "PATCH", // FastAPI update is PATCH
    body, // { is_active }
    auth: true, // owner-only; 404 for someone else's posting id
  })
}

// Query-key factory so the Jobs page and a future invalidateQueries share the same cache entries.
export const postingQueryKeys = {
  all: ["postings"] as const, // prefix for every posting query
  list: () => ["postings", "list"] as const, // GET /postings
}
