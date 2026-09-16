import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query" // list + PATCH is_active
import { useState } from "react" // is_active filter + per-row errors

import { adminQueryKeys, listAdminPostings, patchAdminPosting } from "@/api/admin" // GET/PATCH /admin/postings
import { ApiError } from "@/api/types" // FastAPI detail
import type { AdminPostingOut } from "@/api/types" // list row shape
import { Button } from "@/components/ui/button" // deactivate / reactivate
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // page chrome
import { Skeleton } from "@/components/ui/skeleton" // list loading placeholder

// One posting row from any recruiter: title, owner email, active/embedding badges, deactivate.
function PostingRow({ posting, onChanged }: { posting: AdminPostingOut; onChanged: () => void }) {
  const [error, setError] = useState<string | null>(null) // PATCH failure for this one row

  const patch = useMutation({
    mutationFn: (isActive: boolean) => patchAdminPosting(posting.id, { is_active: isActive }),
    onSuccess: onChanged,
    onError: (caught) => {
      setError(caught instanceof ApiError ? caught.detail : "could not update — is the API running?")
    },
  })

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-1">
          <h3 className="text-sm font-medium">{posting.title}</h3>
          <p className="line-clamp-2 text-xs text-muted-foreground">{posting.description}</p>
          <p className="text-xs text-muted-foreground">Owner: {posting.recruiter_email}</p>
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className={`rounded-full border px-2 py-0.5 text-xs font-medium ${
              posting.is_active
                ? "border-primary/30 bg-primary/10 text-primary"
                : "border-border bg-muted text-muted-foreground"
            }`}
          >
            {posting.is_active ? "Active" : "Inactive"}
          </span>
          <span className="rounded-full border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground">
            {posting.has_embedding ? "Embedded" : "No embedding"}
          </span>
        </div>
      </div>
      {posting.required_skills ? (
        <p className="text-xs text-muted-foreground">Skills: {posting.required_skills}</p>
      ) : null}
      {error !== null ? (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      {posting.is_active ? (
        <div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={patch.isPending}
            onClick={() => {
              setError(null)
              patch.mutate(false)
            }}
          >
            {patch.isPending ? "Updating…" : "Deactivate"}
          </Button>
        </div>
      ) : (
        <div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={patch.isPending}
            onClick={() => {
              setError(null)
              patch.mutate(true)
            }}
          >
            {patch.isPending ? "Updating…" : "Reactivate"}
          </Button>
        </div>
      )}
    </div>
  )
}

// Admin Postings: every recruiter's jobs. GET /postings stays own-only; this list is /admin/postings.
export function AdminPostingsPage() {
  const queryClient = useQueryClient() // invalidate after PATCH
  const [activeFilter, setActiveFilter] = useState<"" | "true" | "false">("") // empty = both

  const params = {
    is_active: activeFilter === "" ? undefined : activeFilter === "true", // FastAPI bool
  }

  const postingsQuery = useQuery({
    queryKey: adminQueryKeys.postings(params), // GET /admin/postings
    queryFn: () => listAdminPostings(params), // newest first
  })

  const postingsError =
    postingsQuery.error instanceof ApiError
      ? postingsQuery.error.detail
      : postingsQuery.isError
        ? "could not load postings — is the API running?"
        : null

  async function onChanged() {
    await queryClient.invalidateQueries({ queryKey: adminQueryKeys.all }) // refresh admin lists
  }

  return (
    <Card data-testid="admin-postings">
      <CardHeader>
        <CardTitle>Postings</CardTitle>
        <CardDescription>
          Cross-recruiter list. Deactivate with is_active — there is no hard delete. This is not async job status
          (`GET /jobs/:id`).
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <label className="flex max-w-xs flex-col gap-1 text-sm">
          <span className="text-muted-foreground">Active</span>
          <select
            className="h-9 rounded-lg border border-input bg-background px-3 text-sm"
            value={activeFilter}
            onChange={(event) => {
              setActiveFilter(event.target.value as "" | "true" | "false") // refetch
            }}
          >
            <option value="">Active and inactive</option>
            <option value="true">Active only</option>
            <option value="false">Inactive only</option>
          </select>
        </label>
        {postingsQuery.isPending ? <Skeleton className="h-24 w-full" /> : null}
        {postingsError !== null ? (
          <p className="text-sm text-destructive" role="alert">
            {postingsError}
          </p>
        ) : null}
        {postingsQuery.data !== undefined && postingsQuery.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">No postings match these filters.</p>
        ) : null}
        {postingsQuery.data !== undefined
          ? postingsQuery.data.map((posting) => (
              <PostingRow key={posting.id} posting={posting} onChanged={() => void onChanged()} />
            ))
          : null}
      </CardContent>
    </Card>
  )
}
