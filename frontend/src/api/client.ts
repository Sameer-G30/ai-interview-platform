// Typed fetch wrapper with a single-flight refresh interceptor for opaque (non-JWT) refresh tokens.

import { ApiError, type TokenPairResponse } from "@/api/types" // error class + refresh response shape
import { clearTokens, getTokens, setTokens, tokensFromResponse } from "@/api/token-store" // session persistence

// HTTP verbs the client is willing to send; keeps call sites from passing arbitrary strings.
export type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE" // matches what FastAPI routes use

// Options for one API call; `auth` defaults to true so protected endpoints cannot forget the header.
export type ApiRequestOptions = {
  method?: HttpMethod // defaults to GET
  body?: unknown // JSON-encoded when present; omitted for GET / 204-style calls
  auth?: boolean // when true (default), attach the access token if we have one
  skipRefresh?: boolean // when true, a 401 is returned as an error instead of triggering rotation
  headers?: Record<string, string> // extra headers merged after Content-Type / Authorization
}

// In-flight refresh promise so concurrent 401s share one POST /auth/refresh (rotation is single-use).
let refreshInFlight: Promise<boolean> | null = null // null means no refresh is running right now

// Resolves the FastAPI origin, stripping a trailing slash so path joins stay predictable.
export function getApiBaseUrl(): string {
  const raw = import.meta.env.VITE_API_BASE_URL // optional override from frontend/.env
  if (typeof raw === "string" && raw.trim().length > 0) {
    return raw.replace(/\/+$/, "") // "http://127.0.0.1:8001/" -> "http://127.0.0.1:8001"
  }
  if (import.meta.env.DEV) {
    return "" // same-origin; Vite proxies /auth, /health, /jobs, /resumes, /postings, /matches, /interviews to uvicorn (avoids CORS)
  }
  return "http://localhost:8000" // production-style default when no VITE_API_BASE_URL is set
}

// Pulls a human-readable string out of FastAPI's `detail` field (string or 422 list).
function detailFromBody(body: unknown, fallback: string): string {
  if (typeof body !== "object" || body === null || !("detail" in body)) {
    return fallback // non-JSON or unexpected shape
  }
  const detail: unknown = (body as { detail: unknown }).detail // FastAPI's standard error key
  if (typeof detail === "string" && detail.length > 0) {
    return detail // 401/409/429 typically look like this
  }
  if (Array.isArray(detail)) {
    const parts = detail.map((item: unknown) => {
      if (typeof item === "object" && item !== null && "msg" in item) {
        return String((item as { msg: unknown }).msg) // Pydantic 422 item
      }
      return JSON.stringify(item) // unknown list entry; still surface something
    })
    const joined = parts.filter((part) => part.length > 0).join("; ") // combine field errors
    return joined.length > 0 ? joined : fallback // empty list falls back
  }
  return fallback // detail was some other JSON type
}

// Parses a response body as JSON when present; 204 and empty bodies become undefined.
async function readBody(response: Response): Promise<unknown> {
  if (response.status === 204) {
    return undefined // logout returns No Content
  }
  const text = await response.text() // read once; response.json() would fail on empty bodies
  if (text.length === 0) {
    return undefined // no payload
  }
  try {
    return JSON.parse(text) as unknown // FastAPI JSON
  } catch {
    return text // unexpected non-JSON; keep the raw text for the error message
  }
}

// Low-level fetch that never attempts token refresh (used by the interceptor itself).
async function rawRequest(path: string, options: ApiRequestOptions, accessToken: string | null): Promise<Response> {
  const method = options.method ?? "GET" // default verb
  const headers = new Headers(options.headers) // copy so we can set Content-Type / Authorization
  headers.set("Accept", "application/json") // we always want JSON back from this API
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json") // JSON body for register/login/refresh/logout
  }
  if (options.auth !== false && accessToken !== null) {
    headers.set("Authorization", `Bearer ${accessToken}`) // access JWT; refresh tokens never go here
  }
  const url = `${getApiBaseUrl()}${path.startsWith("/") ? path : `/${path}`}` // join origin + path
  return fetch(url, {
    method, // GET/POST/...
    headers, // Accept / Content-Type / Authorization
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined, // encode JSON when present
    credentials: "omit", // we send Bearer tokens, not cookies, so omit cookies
  })
}

// Runs POST /auth/refresh at most once at a time; returns false and clears the session on failure.
async function refreshSession(): Promise<boolean> {
  if (refreshInFlight !== null) {
    return refreshInFlight // join the in-flight rotation instead of starting a second one
  }
  refreshInFlight = (async () => {
    const tokens = getTokens() // latest pair from the store
    if (tokens === null) {
      return false // nothing to rotate
    }
    try {
      const response = await rawRequest(
        "/auth/refresh",
        {
          method: "POST", // refresh is a POST with a JSON body
          body: { refresh_token: tokens.refreshToken }, // opaque token, matching RefreshRequest
          auth: false, // do not send the expired access JWT; the body is the credential
          skipRefresh: true, // belt-and-suspenders: never recurse if this 401s
        },
        null, // no Authorization header
      )
      if (!response.ok) {
        clearTokens() // invalid/reused refresh token; drop the session so guards send the user to login
        return false // caller will surface 401
      }
      const payload = (await readBody(response)) as TokenPairResponse // { access_token, refresh_token, token_type }
      setTokens(tokensFromResponse(payload)) // store the rotated pair; the old refresh token is now dead
      return true // original request may retry with the new access token
    } catch {
      clearTokens() // network failure during refresh; safer to sign out than retry blindly
      return false // caller treats this as unauthenticated
    }
  })().finally(() => {
    refreshInFlight = null // allow a later 401 to start a new refresh
  })
  return refreshInFlight // both the first and joined callers await the same promise
}

// Public typed fetch: JSON in/out, ApiError on failure, one refresh-and-retry on 401.
export async function apiFetch<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const auth = options.auth !== false // default to attaching the access token
  const skipRefresh = options.skipRefresh === true // login/register/refresh/logout pass true as needed
  const firstTokens = getTokens() // may be null for public endpoints
  let response: Response
  try {
    response = await rawRequest(path, options, auth ? (firstTokens?.accessToken ?? null) : null) // first attempt
  } catch {
    throw new ApiError(0, `could not reach the API at ${getApiBaseUrl() || window.location.origin}`) // network / CORS
  }
  if (response.status === 401 && auth && !skipRefresh) {
    const refreshed = await refreshSession() // single-flight rotation of the opaque refresh token
    if (refreshed) {
      const retryTokens = getTokens() // pair written by refreshSession
      try {
        response = await rawRequest(path, { ...options, skipRefresh: true }, retryTokens?.accessToken ?? null) // one retry
      } catch {
        throw new ApiError(0, `could not reach the API at ${getApiBaseUrl() || window.location.origin}`) // retry network / CORS
      }
    }
  }
  const body = await readBody(response) // JSON or undefined
  if (!response.ok) {
    const fallback = response.status === 429 ? "too many requests — try again in a minute" : "request failed"
    throw new ApiError(response.status, detailFromBody(body, fallback)) // UI displays .detail
  }
  return body as T // caller is responsible for the expected success shape
}

// Options for multipart upload; `onProgress` is 0–100 from XMLHttpRequest (fetch has no upload progress).
export type ApiUploadOptions = {
  auth?: boolean // when true (default), attach the access token if we have one
  skipRefresh?: boolean // when true, a 401 is returned as an error instead of triggering rotation
  onProgress?: (percent: number) => void // called as bytes leave the browser; 100 does not mean the worker finished
}

// Sends one XMLHttpRequest with a FormData body; never sets Content-Type so the browser supplies the boundary.
function rawUpload(
  path: string, // API path beginning with /
  formData: FormData, // multipart body; field name is chosen by the caller (resumes use `file`)
  accessToken: string | null, // Bearer token or null for a public upload (none exist today)
  onProgress?: (percent: number) => void, // optional 0–100 callback from xhr.upload.onprogress
): Promise<{ status: number; body: unknown }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest() // XHR is required for upload progress; fetch cannot report it
    const url = `${getApiBaseUrl()}${path.startsWith("/") ? path : `/${path}`}` // same origin join as rawRequest
    xhr.open("POST", url) // resume upload is always POST
    xhr.setRequestHeader("Accept", "application/json") // we still want FastAPI JSON back
    if (accessToken !== null) {
      xhr.setRequestHeader("Authorization", `Bearer ${accessToken}`) // access JWT; do not set Content-Type
    }
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable || onProgress === undefined) {
        return // some browsers omit total; skip rather than reporting NaN
      }
      onProgress(Math.round((event.loaded / event.total) * 100)) // 0–100 integer for the progress bar
    }
    xhr.onload = () => {
      const text = xhr.responseText // read once; empty bodies are valid
      let parsed: unknown = undefined // 201 JSON or an error detail object
      if (text.length > 0) {
        try {
          parsed = JSON.parse(text) as unknown // FastAPI JSON
        } catch {
          parsed = text // unexpected non-JSON; keep the raw text for the error message
        }
      }
      resolve({ status: xhr.status, body: parsed }) // caller decides ok vs ApiError
    }
    xhr.onerror = () => {
      reject(new ApiError(0, `could not reach the API at ${getApiBaseUrl() || window.location.origin}`)) // network / CORS
    }
    xhr.send(formData) // browser sets multipart/form-data with the correct boundary
  })
}

// Public multipart POST: FormData in, JSON out, ApiError on failure, one refresh-and-retry on 401.
export async function apiUpload<T>(path: string, formData: FormData, options: ApiUploadOptions = {}): Promise<T> {
  const auth = options.auth !== false // default to attaching the access token
  const skipRefresh = options.skipRefresh === true // not used by resume upload today; kept for symmetry with apiFetch
  const firstTokens = getTokens() // may be null if the session was cleared
  let result: { status: number; body: unknown }
  try {
    result = await rawUpload(path, formData, auth ? (firstTokens?.accessToken ?? null) : null, options.onProgress) // first attempt
  } catch (error) {
    if (error instanceof ApiError) {
      throw error // already a typed network error from xhr.onerror
    }
    throw new ApiError(0, `could not reach the API at ${getApiBaseUrl() || window.location.origin}`) // unexpected throw
  }
  if (result.status === 401 && auth && !skipRefresh) {
    const refreshed = await refreshSession() // single-flight rotation of the opaque refresh token
    if (refreshed) {
      const retryTokens = getTokens() // pair written by refreshSession
      try {
        result = await rawUpload(path, formData, retryTokens?.accessToken ?? null, options.onProgress) // one retry
      } catch (error) {
        if (error instanceof ApiError) {
          throw error // typed network error on the retry
        }
        throw new ApiError(0, `could not reach the API at ${getApiBaseUrl() || window.location.origin}`) // unexpected throw
      }
    }
  }
  if (result.status < 200 || result.status >= 300) {
    const fallback = result.status === 429 ? "too many requests — try again in a minute" : "request failed"
    throw new ApiError(result.status, detailFromBody(result.body, fallback)) // UI displays .detail
  }
  return result.body as T // caller is responsible for the expected success shape
}
