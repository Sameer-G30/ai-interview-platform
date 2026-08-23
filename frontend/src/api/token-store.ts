// Module-level token store: localStorage persistence plus in-tab pub/sub for React and the interceptor.

import type { AuthTokens } from "@/api/types" // the camelCase pair the rest of the client uses

// localStorage key; namespaced so it will not collide with other apps on localhost.
const STORAGE_KEY = "aiip.auth.tokens" // "aiip" = AI Interview Platform

// Listeners notified whenever the in-memory pair is replaced or cleared (same-tab updates).
const listeners = new Set<(tokens: AuthTokens | null) => void>() // AuthProvider subscribes here

// True only in a real browser; guards against evaluating localStorage during Node tooling.
function canUseStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined" // window is missing in Node
}

// Reads and validates the stored JSON; returns null if missing or corrupt so the user just logs in again.
function readStoredTokens(): AuthTokens | null {
  if (!canUseStorage()) {
    return null // no persistence available (should not happen in the Vite SPA)
  }
  const raw = window.localStorage.getItem(STORAGE_KEY) // null when the user has never logged in
  if (raw === null) {
    return null // first visit or after logout
  }
  try {
    const parsed: unknown = JSON.parse(raw) // may throw on corrupt JSON
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "accessToken" in parsed &&
      "refreshToken" in parsed &&
      typeof parsed.accessToken === "string" &&
      typeof parsed.refreshToken === "string" &&
      parsed.accessToken.length > 0 &&
      parsed.refreshToken.length > 0
    ) {
      return { accessToken: parsed.accessToken, refreshToken: parsed.refreshToken } // both halves present
    }
    window.localStorage.removeItem(STORAGE_KEY) // drop unusable payloads rather than looping on them
    return null // treat as signed-out
  } catch {
    window.localStorage.removeItem(STORAGE_KEY) // JSON.parse failed; clear the bad value
    return null // treat as signed-out
  }
}

// In-memory copy so the interceptor does not re-parse JSON on every request.
let currentTokens: AuthTokens | null = readStoredTokens() // hydrated once at module load in the browser

// Returns the current pair, or null when the session is empty.
export function getTokens(): AuthTokens | null {
  return currentTokens // interceptor and AuthProvider both read this
}

// Persists a new pair (or clears storage), then notifies every subscriber in this tab.
export function setTokens(tokens: AuthTokens | null): void {
  currentTokens = tokens // keep the interceptor's view in sync immediately
  if (canUseStorage()) {
    if (tokens === null) {
      window.localStorage.removeItem(STORAGE_KEY) // logout / failed refresh
    } else {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(tokens)) // survive a full page reload
    }
  }
  for (const listener of listeners) {
    listener(tokens) // AuthProvider setState so React re-renders with the new session
  }
}

// Convenience wrapper used by logout and failed-refresh paths.
export function clearTokens(): void {
  setTokens(null) // single path for "no session"
}

// Subscribe to token changes; returns an unsubscribe function for useEffect cleanup.
export function subscribeTokens(listener: (tokens: AuthTokens | null) => void): () => void {
  listeners.add(listener) // AuthProvider calls this on mount
  return () => {
    listeners.delete(listener) // AuthProvider calls this on unmount to avoid leaks
  }
}

// Maps FastAPI's snake_case token JSON onto the camelCase store shape.
export function tokensFromResponse(payload: { access_token: string; refresh_token: string }): AuthTokens {
  return {
    accessToken: payload.access_token, // JWT for Authorization headers
    refreshToken: payload.refresh_token, // opaque value posted to /auth/refresh
  }
}

