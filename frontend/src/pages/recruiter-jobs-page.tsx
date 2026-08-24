import { zodResolver } from "@hookform/resolvers/zod" // adapter that runs the Zod schema inside react-hook-form
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query" // create mutation + list query
import { useState } from "react" // per-posting "deactivating" id + top-level API error banner
import { Controller, useForm } from "react-hook-form" // form state, validation, and submit handler

import { createPosting, listPostings, postingQueryKeys, updatePosting } from "@/api/postings" // typed /postings client
import { ApiError } from "@/api/types" // FastAPI detail for the error banner
import type { PostingOut } from "@/api/types" // list item shape
import { Button } from "@/components/ui/button" // submit + deactivate actions
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // page chrome
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field" // accessible field wrapper
import { Input } from "@/components/ui/input" // title input
import { Skeleton } from "@/components/ui/skeleton" // list loading placeholder
import { Textarea } from "@/components/ui/textarea" // description / required_skills inputs
import { createPostingSchema, type CreatePostingValues } from "@/lib/schemas" // Zod schema + inferred form type

// One posting row: title, active/inactive + embedding badges, and a deactivate button when active.
function PostingRow({ posting, onDeactivated }: { posting: PostingOut; onDeactivated: () => void }) {
  const [error, setError] = useState<string | null>(null) // PATCH failure for this one row

  const deactivate = useMutation({
    mutationFn: () => updatePosting(posting.id, { is_active: false }),
    onSuccess: onDeactivated,
    onError: (caught) => {
      setError(caught instanceof ApiError ? caught.detail : "could not update — is the API running?")
    },
  })

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-medium">{posting.title}</h3>
          <p className="line-clamp-2 text-xs text-muted-foreground">{posting.description}</p>
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
            {posting.has_embedding ? "Embedded" : "Embedding…"}
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
            disabled={deactivate.isPending}
            onClick={() => {
              setError(null)
              deactivate.mutate()
            }}
          >
            {deactivate.isPending ? "Deactivating…" : "Deactivate"}
          </Button>
        </div>
      ) : null}
    </div>
  )
}

// Recruiter-only Jobs page: create a posting (title/description/required_skills), list own postings.
export function RecruiterJobsPage() {
  const queryClient = useQueryClient() // invalidate the list after create/deactivate
  const [apiError, setApiError] = useState<string | null>(null) // FastAPI detail from a failed create

  const postingsQuery = useQuery({
    queryKey: postingQueryKeys.list(),
    queryFn: listPostings,
  })

  const form = useForm<CreatePostingValues>({
    resolver: zodResolver(createPostingSchema),
    defaultValues: { title: "", description: "", required_skills: "" },
  })

  const create = useMutation({
    mutationFn: (values: CreatePostingValues) =>
      createPosting({
        title: values.title,
        description: values.description,
        required_skills: values.required_skills?.trim() ? values.required_skills.trim() : null,
      }),
    onSuccess: async () => {
      form.reset({ title: "", description: "", required_skills: "" }) // clear the form for the next posting
      await queryClient.invalidateQueries({ queryKey: postingQueryKeys.list() }) // show the new row immediately
    },
    onError: (caught) => {
      setApiError(caught instanceof ApiError ? caught.detail : "could not create posting — is the API running?")
    },
  })

  async function onSubmit(values: CreatePostingValues) {
    setApiError(null)
    await create.mutateAsync(values)
  }

  const postingsError =
    postingsQuery.error instanceof ApiError
      ? postingsQuery.error.detail
      : postingsQuery.isError
        ? "could not load postings"
        : null

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold">Jobs</h1>
        <p className="text-muted-foreground">
          Create postings and see which candidates match. Embedding runs on the ARQ worker after you submit.
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>New posting</CardTitle>
          <CardDescription>Title, description, and an optional freeform list of required skills.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
            <FieldGroup>
              <Controller
                name="title"
                control={form.control}
                render={({ field, fieldState }) => (
                  <Field data-invalid={fieldState.invalid}>
                    <FieldLabel htmlFor={field.name}>Title</FieldLabel>
                    <Input {...field} id={field.name} aria-invalid={fieldState.invalid} />
                    {fieldState.invalid && <FieldError errors={[fieldState.error]} />}
                  </Field>
                )}
              />
              <Controller
                name="description"
                control={form.control}
                render={({ field, fieldState }) => (
                  <Field data-invalid={fieldState.invalid}>
                    <FieldLabel htmlFor={field.name}>Description</FieldLabel>
                    <Textarea {...field} id={field.name} rows={4} aria-invalid={fieldState.invalid} />
                    {fieldState.invalid && <FieldError errors={[fieldState.error]} />}
                  </Field>
                )}
              />
              <Controller
                name="required_skills"
                control={form.control}
                render={({ field, fieldState }) => (
                  <Field data-invalid={fieldState.invalid}>
                    <FieldLabel htmlFor={field.name}>Required skills (optional)</FieldLabel>
                    <Textarea
                      {...field}
                      id={field.name}
                      rows={2}
                      placeholder="Python, FastAPI, PostgreSQL"
                      aria-invalid={fieldState.invalid}
                    />
                    {fieldState.invalid && <FieldError errors={[fieldState.error]} />}
                  </Field>
                )}
              />
            </FieldGroup>
            {apiError !== null ? (
              <p className="text-sm text-destructive" role="alert">
                {apiError}
              </p>
            ) : null}
            <Button type="submit" disabled={form.formState.isSubmitting || create.isPending}>
              {create.isPending ? "Creating…" : "Create posting"}
            </Button>
          </form>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Your postings</CardTitle>
          <CardDescription>Newest first.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {postingsQuery.isPending ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-16 w-full" />
            </div>
          ) : null}
          {postingsError !== null ? (
            <p className="text-sm text-destructive" role="alert">
              {postingsError}
            </p>
          ) : null}
          {postingsQuery.data !== undefined && postingsQuery.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">No postings yet — create one above.</p>
          ) : null}
          {postingsQuery.data?.map((posting) => (
            <PostingRow
              key={posting.id}
              posting={posting}
              onDeactivated={() => {
                void queryClient.invalidateQueries({ queryKey: postingQueryKeys.list() })
              }}
            />
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
