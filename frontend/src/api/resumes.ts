// Typed wrappers around Phase 5 `/resumes/*` endpoints. Auth is on by default.

import { apiFetch, apiUpload } from "@/api/client" // JSON GET plus multipart POST with upload progress
import type { ResumeOut, ResumeUploadOut } from "@/api/types" // FastAPI JSON contracts for upload/results

export const MAX_RESUME_BYTES = 10 * 1024 * 1024 // matches backend _MAX_UPLOAD_BYTES (10 MiB), checked in the browser first

export const RESUME_ACCEPT = "application/pdf,.pdf" // PDF-only; the API also rejects any other content type

// True when the file looks like a PDF by MIME type or by filename (some browsers leave type empty on drop).
export function isPdfFile(file: File): boolean {
  const mimeOk = file.type === "application/pdf" // Chromium usually sets this on <input type="file">
  const nameOk = file.name.toLowerCase().endsWith(".pdf") // drag-and-drop from some OSes reports type=""
  return mimeOk || nameOk // either signal is enough; the API still validates Content-Type
}

// POST /resumes — multipart field name is `file`; reports 0–100 upload progress via onProgress.
export async function uploadResume(
  file: File, // already validated as PDF and ≤ 10 MiB by the dropzone
  onProgress?: (percent: number) => void, // XHR upload progress; 100 does not mean parsing finished
): Promise<ResumeUploadOut> {
  const formData = new FormData() // multipart body; do not JSON.stringify
  formData.append("file", file, file.name) // FastAPI UploadFile field is named `file`
  return apiUpload<ResumeUploadOut>("/resumes", formData, {
    auth: true, // owner is taken from the access JWT
    onProgress, // forwarded to XMLHttpRequest.upload.onprogress
  })
}

// GET /resumes/{id} — owner-only results read; 404 for missing or someone else's resume.
export async function fetchResume(resumeId: string): Promise<ResumeOut> {
  return apiFetch<ResumeOut>(`/resumes/${resumeId}`, {
    method: "GET", // FastAPI results poll is GET
    auth: true, // interceptor will rotate the opaque refresh token on 401
  })
}

// Query-key factory so the results page and a future invalidateQueries share the same cache entries.
export const resumeQueryKeys = {
  all: ["resumes"] as const, // prefix for every resume query
  detail: (resumeId: string) => ["resumes", "detail", resumeId] as const, // GET /resumes/{id}
}
