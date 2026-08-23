import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react" // React primitives for the session provider

import { useQuery, useQueryClient } from "@tanstack/react-query" // caches GET /auth/me and lets logout drop it

import { authQueryKeys, fetchCurrentUser, loginAccount, logoutAccount, registerAccount } from "@/api/auth" // Phase 2 auth HTTP helpers
import { ApiError, type AuthTokens, type CurrentUser, type LoginRequest, type RegisterRequest } from "@/api/types" // session types + error class
import { clearTokens, getTokens, setTokens, subscribeTokens } from "@/api/token-store" // localStorage-backed token pair
import { AuthContext, type AuthContextValue } from "@/lib/auth-context" // context object lives in a .ts file so this module only exports a component

// Props for the provider: only children, so App.tsx can wrap the router.
type AuthProviderProps = {
  children: ReactNode // the RouterProvider (and Toaster) live under this so every route can call useAuth
}

// Owns the session: token subscription, /auth/me query, and login/register/logout mutations.
export function AuthProvider({ children }: AuthProviderProps) {
  const queryClient = useQueryClient() // the QueryClient created in App.tsx
  const [tokens, setTokenState] = useState<AuthTokens | null>(() => getTokens()) // hydrate from localStorage on first render

  useEffect(() => {
    return subscribeTokens((next) => {
      setTokenState(next) // interceptor refresh / logout in another helper still updates React
    })
  }, []) // subscribe once for the lifetime of the provider

  const hasRefreshToken = Boolean(tokens?.refreshToken) // /auth/me is only enabled when we have a session

  const meQuery = useQuery({
    queryKey: authQueryKeys.me, // shared with logout's removeQueries so the cache cannot leak a previous user
    queryFn: fetchCurrentUser, // GET /auth/me; apiFetch will rotate the opaque refresh token on 401
    enabled: hasRefreshToken, // skip the network when signed out
    retry: false, // a failed session fetch should not spam /auth/me (refresh already happened inside apiFetch)
  })

  useEffect(() => {
    if (!tokens) {
      queryClient.removeQueries({ queryKey: authQueryKeys.me }) // drop the cached user the moment the store is cleared
    }
  }, [tokens, queryClient]) // runs after interceptor/logout calls clearTokens()

  const login = useCallback(
    async (input: LoginRequest): Promise<CurrentUser> => {
      const pair = await loginAccount(input) // POST /auth/login; throws ApiError on 401/429
      setTokens(pair) // persist access+refresh before fetching /auth/me
      try {
        return await queryClient.fetchQuery({
          queryKey: authQueryKeys.me, // populate the same key useQuery reads
          queryFn: fetchCurrentUser, // GET /auth/me with the new access token
        })
      } catch (error) {
        clearTokens() // login succeeded but /auth/me failed; do not leave a half-session in localStorage
        throw error // rethrow so the login form can display the message
      }
    },
    [queryClient], // fetchQuery is bound to this client
  )

  const register = useCallback(
    async (input: RegisterRequest): Promise<CurrentUser> => {
      const pair = await registerAccount(input) // POST /auth/register; throws ApiError on 409/422/429
      setTokens(pair) // new accounts are logged in immediately, matching the API
      try {
        return await queryClient.fetchQuery({
          queryKey: authQueryKeys.me, // same cache as login
          queryFn: fetchCurrentUser, // confirm the session server-side
        })
      } catch (error) {
        clearTokens() // do not keep tokens if we cannot load the user
        throw error // surface to the register form
      }
    },
    [queryClient], // fetchQuery is bound to this client
  )

  const logout = useCallback(async (): Promise<void> => {
    const refreshToken = getTokens()?.refreshToken // capture before we clear, so the API can revoke it
    try {
      if (refreshToken) {
        await logoutAccount(refreshToken) // POST /auth/logout; backend always 204s even if already revoked
      }
    } catch (error) {
      if (!(error instanceof ApiError)) {
        throw error // unexpected non-API failure; still unusual for logout
      }
    } finally {
      clearTokens() // always drop the local pair
      queryClient.removeQueries({ queryKey: authQueryKeys.me }) // forget the user row
    }
  }, [queryClient]) // removeQueries needs this client

  const value = useMemo<AuthContextValue>(
    () => ({
      user: hasRefreshToken && meQuery.data ? meQuery.data : null, // never return a cached user after logout
      tokens, // exposed so guards can distinguish "no tokens" from "tokens, waiting on /me"
      isLoading: hasRefreshToken && meQuery.isPending, // spinner while restoring a session from localStorage
      isError: hasRefreshToken && meQuery.isError, // tokens exist but /auth/me failed
      login, // form pages call this
      register, // form pages call this
      logout, // sidebar user menu calls this
    }),
    [hasRefreshToken, meQuery.data, meQuery.isPending, meQuery.isError, tokens, login, register, logout], // recompute when session state changes
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider> // descendants call useAuth()
}
