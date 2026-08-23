import { zodResolver } from "@hookform/resolvers/zod" // adapter that runs the Zod schema inside react-hook-form
import { useState } from "react" // local state for the API-level error string
import { Controller, useForm } from "react-hook-form" // form state, validation, and submit handler
import { Link, useNavigate } from "react-router-dom" // login link + post-register redirect

import { ApiError } from "@/api/types" // used to pull FastAPI's `detail` into the form error banner
import { Button } from "@/components/ui/button" // submit button
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // form chrome
import { Field, FieldError, FieldGroup, FieldLabel, FieldLegend, FieldSet, FieldTitle } from "@/components/ui/field" // accessible field wrapper
import { Input } from "@/components/ui/input" // email/password/name inputs
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group" // candidate vs recruiter (never admin)
import { useAuth } from "@/hooks/use-auth" // register() stores tokens then loads /auth/me
import { homePathForUser } from "@/lib/home-path" // /candidate or /recruiter after success
import { registerSchema, type RegisterValues } from "@/lib/schemas" // Zod schema + inferred form type

// Register page: React Hook Form + Zod, then POST /auth/register (is_admin cannot be set here).
export function RegisterPage() {
  const { register } = useAuth() // mutation-like helper from AuthProvider
  const navigate = useNavigate() // send the user to their role home after a successful register
  const [apiError, setApiError] = useState<string | null>(null) // FastAPI detail, e.g. duplicate email

  const form = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema), // run Zod on submit
    defaultValues: { email: "", password: "", full_name: "", role: "candidate" }, // candidate is the product default
  })

  async function onSubmit(values: RegisterValues) {
    setApiError(null) // clear a previous server error when the user tries again
    const fullName = values.full_name?.trim() ?? "" // treat whitespace-only as omitted
    try {
      const user = await register({
        email: values.email, // required
        password: values.password, // 8–128 chars, already validated by Zod
        full_name: fullName.length > 0 ? fullName : null, // FastAPI accepts null
        role: values.role, // candidate | recruiter; never sends is_admin
      })
      navigate(homePathForUser(user), { replace: true }) // land on the matching home; replace so Back skips register
    } catch (error) {
      if (error instanceof ApiError) {
        setApiError(error.detail) // 409 email taken, 422 validation, 429 rate limit
        return // stay on the form
      }
      setApiError("could not register — is the API running?") // network / unexpected
    }
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Create an account</CardTitle>
        <CardDescription>Candidates practice interviews. Recruiters review applicants. Admin is granted later by an operator.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={form.handleSubmit(onSubmit)} noValidate className="flex flex-col gap-4">
          <FieldGroup>
            <Controller
              name="email"
              control={form.control}
              render={({ field, fieldState }) => (
                <Field data-invalid={fieldState.invalid}>
                  <FieldLabel htmlFor={field.name}>Email</FieldLabel>
                  <Input
                    {...field}
                    id={field.name}
                    type="email"
                    autoComplete="email"
                    aria-invalid={fieldState.invalid}
                  />
                  {fieldState.invalid && <FieldError errors={[fieldState.error]} />}
                </Field>
              )}
            />
            <Controller
              name="full_name"
              control={form.control}
              render={({ field, fieldState }) => (
                <Field data-invalid={fieldState.invalid}>
                  <FieldLabel htmlFor={field.name}>Full name (optional)</FieldLabel>
                  <Input
                    {...field}
                    id={field.name}
                    type="text"
                    autoComplete="name"
                    aria-invalid={fieldState.invalid}
                  />
                  {fieldState.invalid && <FieldError errors={[fieldState.error]} />}
                </Field>
              )}
            />
            <Controller
              name="password"
              control={form.control}
              render={({ field, fieldState }) => (
                <Field data-invalid={fieldState.invalid}>
                  <FieldLabel htmlFor={field.name}>Password</FieldLabel>
                  <Input
                    {...field}
                    id={field.name}
                    type="password"
                    autoComplete="new-password"
                    aria-invalid={fieldState.invalid}
                  />
                  {fieldState.invalid && <FieldError errors={[fieldState.error]} />}
                </Field>
              )}
            />
            <Controller
              name="role"
              control={form.control}
              render={({ field, fieldState }) => (
                <FieldSet>
                  <FieldLegend>I am a</FieldLegend>
                  <RadioGroup
                    value={field.value}
                    onValueChange={field.onChange}
                    className="grid grid-cols-2 gap-3"
                  >
                    <FieldLabel htmlFor="role-candidate" className="flex items-start gap-2 rounded-lg border p-3">
                      <RadioGroupItem value="candidate" id="role-candidate" />
                      <FieldTitle>Candidate</FieldTitle>
                    </FieldLabel>
                    <FieldLabel htmlFor="role-recruiter" className="flex items-start gap-2 rounded-lg border p-3">
                      <RadioGroupItem value="recruiter" id="role-recruiter" />
                      <FieldTitle>Recruiter</FieldTitle>
                    </FieldLabel>
                  </RadioGroup>
                  {fieldState.invalid && <FieldError errors={[fieldState.error]} />}
                </FieldSet>
              )}
            />
          </FieldGroup>
          {apiError ? (
            <p className="text-sm text-destructive" role="alert">
              {apiError}
            </p>
          ) : null}
          <Button type="submit" disabled={form.formState.isSubmitting}>
            {form.formState.isSubmitting ? "Creating account…" : "Create account"}
          </Button>
          <p className="text-center text-sm text-muted-foreground">
            Already registered?{" "}
            <Link to="/login" className="text-foreground underline-offset-4 hover:underline">
              Sign in
            </Link>
          </p>
        </form>
      </CardContent>
    </Card>
  )
}
