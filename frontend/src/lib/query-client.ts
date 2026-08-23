import { QueryClient } from "@tanstack/react-query" // the cache + retry engine every useQuery/useMutation shares

import { ApiError } from "@/api/types" // used to skip retries on 4xx (401s already refresh inside apiFetch)

// Builds the one QueryClient instance mounted at the root of the SPA.
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000, // 30s: avoid refetching /auth/me on every focus during a single page session
        retry: (failureCount, error) => {
          if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
            return false // client errors will not succeed on retry (401 already refreshed inside apiFetch)
          }
          return failureCount < 2 // retry transient 5xx / network twice
        },
      },
    },
  })
}
