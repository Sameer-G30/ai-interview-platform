import { useQuery } from "@tanstack/react-query" // polling cache; refetchInterval stops on a terminal status

import { fetchJob, jobQueryKeys } from "@/api/jobs" // GET /jobs/{id} + stable query keys
import type { AsyncJobOut, AsyncJobStatus } from "@/api/types" // poll payload + status union

const TERMINAL_STATUSES: ReadonlySet<AsyncJobStatus> = new Set(["succeeded", "failed"]) // stop polling once done

const POLL_MS = 1000 // 1s while queued/running; short enough for the demo, long enough not to hammer the API

// Reusable poller for any async job id. Resume/interview screens in later phases should reuse this hook.
export function useJobStatus(jobId: string | null) {
  return useQuery<AsyncJobOut>({
    queryKey: jobId === null ? [...jobQueryKeys.all, "idle"] : jobQueryKeys.detail(jobId), // idle key is never fetched
    queryFn: () => fetchJob(jobId as string), // enabled-gate below guarantees jobId is a string here
    enabled: jobId !== null, // do not hit the API until enqueue has returned an id
    staleTime: 0, // override the app-wide 30s staleTime; job status must not look fresh while queued
    refetchInterval: (query) => {
      const status = query.state.data?.status // last successful poll, if any
      if (status !== undefined && TERMINAL_STATUSES.has(status)) {
        return false // succeeded/failed are terminal; stop the interval
      }
      return POLL_MS // keep polling queued/running (and while the first fetch is in flight)
    },
  })
}
