import { createContext } from "react" // React context used by AuthProvider and useAuth

import type { AuthTokens, CurrentUser, LoginRequest, RegisterRequest } from "@/api/types" // session types shared with the API layer

// Value exposed by AuthProvider through useAuth(); components must not import this context directly.
export type AuthContextValue = {
  user: CurrentUser | null // null when signed out or while /auth/me has not resolved
  tokens: AuthTokens | null // current pair, or null when signed out
  isLoading: boolean // true while we have a refresh token and /auth/me is still in flight
  isError: boolean // true when tokens exist but /auth/me failed after refresh was attempted
  login: (input: LoginRequest) => Promise<CurrentUser> // stores tokens then loads the user
  register: (input: RegisterRequest) => Promise<CurrentUser> // same as login after POST /auth/register
  logout: () => Promise<void> // revokes the refresh token best-effort, then always clears local state
}

// Created once; AuthProvider fills it. useAuth throws if this default is still in play.
export const AuthContext = createContext<AuthContextValue | null>(null) // null means "not inside AuthProvider"
