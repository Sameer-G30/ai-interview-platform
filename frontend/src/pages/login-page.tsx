import { zodResolver } from "@hookform/resolvers/zod" // adapter that runs the Zod schema inside react-hook-form
import { useState } from "react" // local state for the API-level error string
import { Controller, useForm } from "react-hook-form" // form state, validation, and submit handler
import { Link, useNavigate } from "react-router-dom" // register link + post-login redirect

import { ApiError } from "@/api/types" // used to pull FastAPI's `detail` into the form error banner
import { Button } from "@/components/ui/button" // submit button
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // form chrome
import { Field, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field" // accessible field wrapper
import { Input } from "@/components/ui/input" // email/password inputs
import { useAuth } from "@/hooks/use-auth" // login() stores tokens then loads /auth/me
import { homePathForUser } from "@/lib/home-path" // /candidate or /recruiter after success
import { loginSchema, type LoginValues } from "@/lib/schemas" // Zod schema + inferred form type

// Login page: React Hook Form + Zod, then POST /auth/login through the typed client.
export function LoginPage() {
  const { login } = useAuth() // mutation-like helper from AuthProvider
  const navigate = useNavigate() // send the user to their role home after a successful login
  const [apiError, setApiError] = useState<string | null>(null) // FastAPI detail, e.g. "incorrect email or password"

  const form = useForm<LoginValues>({
    resolver: zodResolver(loginSchema), // run Zod on submit (and on change after the first submit, by RHF default)
    defaultValues: { email: "", password: "" }, // empty fields on first paint
  })

  async function onSubmit(values: LoginValues) {
    setApiError(null) // clear a previous server error when the user tries again
    try {
      const user = await login({ email: values.email, password: values.password }) // POST /auth/login then GET /auth/me
      navigate(homePathForUser(user), { replace: true }) // land on /candidate or /recruiter; replace so Back skips login
    } catch (error) {
      if (error instanceof ApiError) {
        setApiError(error.detail) // show FastAPI's message (401, 429, ...)
        return // stay on the form
      }
      setApiError("could not sign in — is the API running?") // network / unexpected
    }
  }

  return (
    <Card className="w-full max-w-md">
      <CardHeader>
        <CardTitle>Sign in</CardTitle>
        <CardDescription>Use the account you registered on this platform.</CardDescription>
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
              name="password"
              control={form.control}
              render={({ field, fieldState }) => (
                <Field data-invalid={fieldState.invalid}>
                  <FieldLabel htmlFor={field.name}>Password</FieldLabel>
                  <Input
                    {...field}
                    id={field.name}
                    type="password"
                    autoComplete="current-password"
                    aria-invalid={fieldState.invalid}
                  />
                  {fieldState.invalid && <FieldError errors={[fieldState.error]} />}
                </Field>
              )}
            />
          </FieldGroup>
          {apiError ? (
            <p className="text-sm text-destructive" role="alert">
              {apiError}
            </p>
          ) : null}
          <Button type="submit" disabled={form.formState.isSubmitting}>
            {form.formState.isSubmitting ? "Signing in…" : "Sign in"}
          </Button>
          <p className="text-center text-sm text-muted-foreground">
            No account yet?{" "}
            <Link to="/register" className="text-foreground underline-offset-4 hover:underline">
              Create one
            </Link>
          </p>
        </form>
      </CardContent>
    </Card>
  )
}
