import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query" // list + PATCH is_active / is_admin
import { useState } from "react" // role / is_active filters + per-row errors

import { adminQueryKeys, listAdminUsers, patchAdminUser } from "@/api/admin" // GET/PATCH /admin/users
import { ApiError } from "@/api/types" // FastAPI detail
import type { UserOut, UserRole } from "@/api/types" // list row shape
import { Button } from "@/components/ui/button" // deactivate / grant-admin
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // page chrome
import { Skeleton } from "@/components/ui/skeleton" // list loading placeholder
import { useAuth } from "@/hooks/use-auth" // hide self-deactivate (API also 409s)

// One user row: email, role, flags, deactivate/reactivate, grant/revoke admin on recruiters.
function UserRow({
  row,
  currentUserId,
  onChanged,
}: {
  row: UserOut // GET /admin/users item
  currentUserId: string | undefined // the signed-in admin; cannot deactivate self
  onChanged: () => void // invalidate the list after PATCH
}) {
  const [error, setError] = useState<string | null>(null) // PATCH failure for this one row
  const isSelf = row.id === currentUserId // API 409s self-deactivate; hide the button too

  const patch = useMutation({
    mutationFn: (body: { is_active?: boolean; is_admin?: boolean }) => patchAdminUser(row.id, body),
    onSuccess: onChanged,
    onError: (caught) => {
      setError(caught instanceof ApiError ? caught.detail : "could not update — is the API running?")
    },
  })

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border p-3" data-testid={`admin-user-${row.email}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-1">
          <h3 className="truncate text-sm font-medium">{row.email}</h3>
          <p className="text-xs text-muted-foreground">{row.full_name || "No display name"}</p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="rounded-full border border-border bg-muted px-2 py-0.5 text-xs text-muted-foreground">
            {row.role}
          </span>
          {row.is_admin ? (
            <span className="rounded-full border border-primary/30 bg-primary/10 px-2 py-0.5 text-xs text-primary">
              admin
            </span>
          ) : null}
          <span
            className={`rounded-full border px-2 py-0.5 text-xs font-medium ${
              row.is_active
                ? "border-primary/30 bg-primary/10 text-primary"
                : "border-border bg-muted text-muted-foreground"
            }`}
          >
            {row.is_active ? "Active" : "Inactive"}
          </span>
        </div>
      </div>
      {error !== null ? (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {row.is_active && !isSelf ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={patch.isPending}
            data-testid={`admin-deactivate-${row.email}`}
            onClick={() => {
              setError(null)
              patch.mutate({ is_active: false })
            }}
          >
            {patch.isPending ? "Updating…" : "Deactivate"}
          </Button>
        ) : null}
        {!row.is_active ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={patch.isPending}
            onClick={() => {
              setError(null)
              patch.mutate({ is_active: true })
            }}
          >
            {patch.isPending ? "Updating…" : "Reactivate"}
          </Button>
        ) : null}
        {row.role === "recruiter" && !row.is_admin ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={patch.isPending}
            onClick={() => {
              setError(null)
              patch.mutate({ is_admin: true })
            }}
          >
            Grant admin
          </Button>
        ) : null}
        {row.role === "recruiter" && row.is_admin && !isSelf ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={patch.isPending}
            onClick={() => {
              setError(null)
              patch.mutate({ is_admin: false })
            }}
          >
            Revoke admin
          </Button>
        ) : null}
      </div>
    </div>
  )
}

// Admin Users: list accounts, filter by role / is_active, soft-disable. is_admin is never set via register.
export function AdminUsersPage() {
  const { user } = useAuth() // current admin id for self-guards
  const queryClient = useQueryClient() // invalidate after PATCH
  const [role, setRole] = useState<UserRole | "">("") // empty = no filter
  const [activeFilter, setActiveFilter] = useState<"" | "true" | "false">("") // empty = both

  const params = {
    role: role === "" ? undefined : role, // omit unused query keys
    is_active: activeFilter === "" ? undefined : activeFilter === "true", // FastAPI bool
  }

  const usersQuery = useQuery({
    queryKey: adminQueryKeys.users(params), // GET /admin/users
    queryFn: () => listAdminUsers(params), // newest first
  })

  const usersError =
    usersQuery.error instanceof ApiError
      ? usersQuery.error.detail
      : usersQuery.isError
        ? "could not load users — is the API running?"
        : null

  async function onChanged() {
    await queryClient.invalidateQueries({ queryKey: adminQueryKeys.all }) // refresh every admin list
  }

  return (
    <Card data-testid="admin-users">
      <CardHeader>
        <CardTitle>Users</CardTitle>
        <CardDescription>
          Soft-disable with is_active. Access JWTs stop working immediately (`GET /auth/me` 401s). Refresh tokens are
          not bulk-revoked; rotation already refuses inactive accounts. Registration cannot set is_admin — set that
          flag in the database (or Grant admin here on a recruiter).
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">Role</span>
            <select
              className="h-9 rounded-lg border border-input bg-background px-3 text-sm"
              value={role}
              data-testid="admin-role-filter"
              onChange={(event) => {
                setRole(event.target.value as UserRole | "") // refetch with ?role=
              }}
            >
              <option value="">All roles</option>
              <option value="candidate">Candidate</option>
              <option value="recruiter">Recruiter</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-muted-foreground">Active</span>
            <select
              className="h-9 rounded-lg border border-input bg-background px-3 text-sm"
              value={activeFilter}
              onChange={(event) => {
                setActiveFilter(event.target.value as "" | "true" | "false") // refetch with ?is_active=
              }}
            >
              <option value="">Active and inactive</option>
              <option value="true">Active only</option>
              <option value="false">Inactive only</option>
            </select>
          </label>
        </div>
        {usersQuery.isPending ? <Skeleton className="h-24 w-full" /> : null}
        {usersError !== null ? (
          <p className="text-sm text-destructive" role="alert">
            {usersError}
          </p>
        ) : null}
        {usersQuery.data !== undefined && usersQuery.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">No users match these filters.</p>
        ) : null}
        {usersQuery.data !== undefined
          ? usersQuery.data.map((row) => (
              <UserRow key={row.id} row={row} currentUserId={user?.id} onChanged={() => void onChanged()} />
            ))
          : null}
      </CardContent>
    </Card>
  )
}
