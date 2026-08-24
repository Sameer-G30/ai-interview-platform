import { useState } from "react" // holds the id of the job this demo is currently polling
import { useMutation } from "@tanstack/react-query" // one-shot POST /jobs/demo

import { enqueueDemoJob } from "@/api/jobs" // throwaway enqueue used only by this Phase 4 demo
import { Button } from "@/components/ui/button" // shadcn button; do not restyle the primitive
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // demo chrome
import { useJobStatus } from "@/hooks/use-job-status" // reusable poller later phases will reuse

// Tiny candidate-home widget that proves enqueue + polling. Not resume upload or interview UI.
export function JobQueueDemo() {
  const [jobId, setJobId] = useState<string | null>(null) // null until the first successful enqueue

  const enqueue = useMutation({
    mutationFn: () => enqueueDemoJob({ message: "hello from the candidate home", sleep_ms: 800 }), // short delay so queued/running is visible
    onSuccess: (job) => {
      setJobId(job.id) // start polling this id; previous demo jobs are left in the table
    },
  })

  const statusQuery = useJobStatus(jobId) // disabled until jobId is set

  const status = statusQuery.data?.status // queued | running | succeeded | failed | undefined
  const resultEcho =
    statusQuery.data?.result !== null &&
    statusQuery.data?.result !== undefined &&
    typeof statusQuery.data.result.echo === "string"
      ? statusQuery.data.result.echo
      : null // demo_echo writes { echo: message }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Queue demo</CardTitle>
        <CardDescription>
          Phase 4 check: enqueue a throwaway echo job and poll GET /jobs/{"{id}"}. Resume upload comes later.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Button
          type="button"
          onClick={() => enqueue.mutate()}
          disabled={enqueue.isPending} // prevent double-clicks while POST is in flight
        >
          {enqueue.isPending ? "Enqueueing…" : "Run demo job"}
        </Button>
        {enqueue.isError ? (
          <p className="text-sm text-destructive">Could not enqueue: {enqueue.error.message}</p>
        ) : null}
        {jobId !== null ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
            <dt className="text-muted-foreground">Job id</dt>
            <dd className="font-mono break-all">{jobId}</dd>
            <dt className="text-muted-foreground">Status</dt>
            <dd>{statusQuery.isPending && status === undefined ? "polling…" : (status ?? "—")}</dd>
            {resultEcho !== null ? (
              <>
                <dt className="text-muted-foreground">Echo</dt>
                <dd>{resultEcho}</dd>
              </>
            ) : null}
            {statusQuery.data?.error ? (
              <>
                <dt className="text-muted-foreground">Error</dt>
                <dd>{statusQuery.data.error}</dd>
              </>
            ) : null}
          </dl>
        ) : null}
      </CardContent>
    </Card>
  )
}
