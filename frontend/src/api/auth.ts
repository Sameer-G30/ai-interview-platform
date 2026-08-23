// Thin wrappers around the Phase 2 `/auth/*` endpoints, returning frontend-friendly types.

import { apiFetch } from "@/api/client" // typed fetch with the refresh interceptor
import { tokensFromResponse } from "@/api/token-store" // snake_case JSON -> camelCase AuthTokens
import type {
  AuthTokens, // access + refresh pair stored after login/register
  CurrentUser, // camelCase user used by AuthProvider and the sidebar
  LoginRequest, // POST /auth/login body
  RegisterRequest, // POST /auth/register body
  TokenPairResponse, // FastAPI TokenPairResponse
  UserOut, // FastAPI UserOut
} from "@/api/types"

// Maps GET /auth/me JSON onto the camelCase CurrentUser the UI consumes.
export function userFromResponse(payload: UserOut): CurrentUser {
  return {
    id: payload.id, // UUID string
    email: payload.email, // normalized email
    fullName: payload.full_name, // optional display name
    role: payload.role, // candidate | recruiter
    isAdmin: payload.is_admin, // extra nav later; not a third role
    isActive: payload.is_active, // false should not appear for a live session
  }
}

// POST /auth/register — creates the account and returns an already-logged-in token pair.
export async function registerAccount(body: RegisterRequest): Promise<AuthTokens> {
  const payload = await apiFetch<TokenPairResponse>("/auth/register", {
    method: "POST", // FastAPI register is POST
    body, // email, password, optional full_name, role
    auth: false, // public endpoint; no bearer token
    skipRefresh: true, // a 409/422 must not attempt token rotation
  })
  return tokensFromResponse(payload) // persist-ready pair
}

// POST /auth/login — verifies credentials and returns a fresh token pair.
export async function loginAccount(body: LoginRequest): Promise<AuthTokens> {
  const payload = await apiFetch<TokenPairResponse>("/auth/login", {
    method: "POST", // FastAPI login is POST
    body, // email + password
    auth: false, // public endpoint
    skipRefresh: true, // a 401 here is bad credentials, not an expired access token
  })
  return tokensFromResponse(payload) // persist-ready pair
}

// POST /auth/logout — revokes the presented refresh token; always succeeds on the server.
export async function logoutAccount(refreshToken: string): Promise<void> {
  await apiFetch<undefined>("/auth/logout", {
    method: "POST", // FastAPI logout is POST
    body: { refresh_token: refreshToken }, // LogoutRequest
    auth: false, // body is the credential; no need for a (possibly expired) access token
    skipRefresh: true, // logout must not rotate the token it is about to revoke
  })
}

// GET /auth/me — protected; the interceptor will rotate the refresh token if the access JWT expired.
export async function fetchCurrentUser(): Promise<CurrentUser> {
  const payload = await apiFetch<UserOut>("/auth/me", {
    method: "GET", // FastAPI me is GET
    auth: true, // attach Authorization: Bearer
  })
  return userFromResponse(payload) // camelCase for React
}

// Query-key factory so AuthProvider and logout invalidate the same cache entry.
export const authQueryKeys = {
  all: ["auth"] as const, // prefix for every auth query
  me: ["auth", "me"] as const, // GET /auth/me
}

