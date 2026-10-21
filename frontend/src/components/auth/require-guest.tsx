import { SparklesIcon } from "lucide-react" // brand mark on the split-screen panel
import { Navigate, Outlet } from "react-router-dom" // redirect signed-in users away from login/register

import { PageSpinner } from "@/components/layout/page-spinner" // wait while we decide if a stored session is valid
import { useAuth } from "@/hooks/use-auth" // current user + loading flag
import { homePathForUser } from "@/lib/home-path" // role-aware landing path after a successful session restore

// Layout guard for /login and /register: signed-in users skip the forms and go to their role home.
export function RequireGuest() {
  const { user, tokens, isLoading } = useAuth() // tokens without user means /auth/me is still running

  if (tokens && isLoading) {
    return <PageSpinner /> // stored session is being restored; do not flash the login form
  }

  if (user) {
    return <Navigate to={homePathForUser(user)} replace /> // already signed in; bounce to /candidate or /recruiter
  }

  return (
    <div className="grid min-h-svh lg:grid-cols-2">
      {/* Brand panel: hidden on mobile so the form gets the whole screen. */}
      <div className="hidden flex-col justify-between bg-primary p-10 text-primary-foreground lg:flex">
        <div className="flex items-center gap-2">
          <div className="flex size-9 items-center justify-center rounded-lg bg-primary-foreground/15">
            <SparklesIcon className="size-5" />
          </div>
          <span className="text-lg font-semibold">Interview Intel</span>
        </div>
        <div className="flex flex-col gap-3">
          <h2 className="text-3xl font-semibold leading-tight">Practice aloud. Get hired with confidence.</h2>
          <p className="max-w-md text-primary-foreground/80">
            Match your resume to real roles, answer interview questions out loud, and get clear feedback on content
            and communication.
          </p>
        </div>
        <p className="text-sm text-primary-foreground/70">AI interview practice and recruiter screening in one place.</p>
      </div>
      <div className="flex items-center justify-center bg-background p-6">
        {/* Guest forms render here: /login or /register. A // comment in JSX would show on the page. */}
        <Outlet />
      </div>
    </div>
  )
}
