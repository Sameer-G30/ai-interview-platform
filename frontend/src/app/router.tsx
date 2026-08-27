import { createBrowserRouter } from "react-router-dom" // data-router used by RouterProvider in App.tsx

import { RequireAuth } from "@/components/auth/require-auth" // session required; redirects to /login
import { RequireGuest } from "@/components/auth/require-guest" // logged-in users skip login/register
import { RequireRole } from "@/components/auth/require-role" // candidate cannot open /recruiter and vice versa
import { RoleLanding } from "@/components/auth/role-landing" // `/` -> login or role home
import { AppShell } from "@/components/layout/app-shell" // sidebar + header around authenticated pages
import { CandidateHomePage } from "@/pages/candidate-home-page" // candidate landing
import { CandidateInterviewSessionPage } from "@/pages/candidate-interview-session-page" // poll generate, answer, poll evaluate
import { CandidateInterviewStartPage } from "@/pages/candidate-interview-start-page" // practice start (POST /interviews {})
import { CandidateMatchesPage } from "@/pages/candidate-matches-page" // ranked postings + skill gap + start interview
import { CandidateResumeResultsPage } from "@/pages/candidate-resume-results-page" // parsed ATS / skills / sections
import { CandidateResumeUploadPage } from "@/pages/candidate-resume-upload-page" // drag-drop PDF upload
import { LoginPage } from "@/pages/login-page" // POST /auth/login form
import { NotFoundPage } from "@/pages/not-found-page" // unknown paths
import { RecruiterHomePage } from "@/pages/recruiter-home-page" // recruiter landing
import { RecruiterJobsPage } from "@/pages/recruiter-jobs-page" // posting create/list/deactivate
import { RegisterPage } from "@/pages/register-page" // POST /auth/register form

// Route tree for the Phase 3 shell: guest forms, role homes, and a 404.
export const router = createBrowserRouter([
  {
    path: "/", // index: bounce to /login or /candidate|/recruiter
    element: <RoleLanding />,
  },
  {
    element: <RequireGuest />, // layout: centered card, redirects away if already signed in
    children: [
      { path: "/login", element: <LoginPage /> }, // public sign-in
      { path: "/register", element: <RegisterPage /> }, // public sign-up (no is_admin)
    ],
  },
  {
    element: <RequireAuth />, // layout: spinner / login redirect / session-error
    children: [
      {
        element: <AppShell />, // sidebar chrome; nested pages render in <Outlet />
        children: [
          {
            path: "/candidate",
            element: (
              <RequireRole role="candidate">
                <CandidateHomePage />
              </RequireRole>
            ),
          },
          {
            path: "/candidate/resume",
            element: (
              <RequireRole role="candidate">
                <CandidateResumeUploadPage />
              </RequireRole>
            ),
          },
          {
            path: "/candidate/resume/:resumeId",
            element: (
              <RequireRole role="candidate">
                <CandidateResumeResultsPage />
              </RequireRole>
            ),
          },
          {
            path: "/candidate/matches",
            element: (
              <RequireRole role="candidate">
                <CandidateMatchesPage />
              </RequireRole>
            ),
          },
          {
            path: "/candidate/interview",
            element: (
              <RequireRole role="candidate">
                <CandidateInterviewStartPage />
              </RequireRole>
            ),
          },
          {
            path: "/candidate/interview/:sessionId",
            element: (
              <RequireRole role="candidate">
                <CandidateInterviewSessionPage />
              </RequireRole>
            ),
          },
          {
            path: "/recruiter",
            element: (
              <RequireRole role="recruiter">
                <RecruiterHomePage />
              </RequireRole>
            ),
          },
          {
            path: "/recruiter/jobs",
            element: (
              <RequireRole role="recruiter">
                <RecruiterJobsPage />
              </RequireRole>
            ),
          },
        ],
      },
    ],
  },
  { path: "*", element: <NotFoundPage /> }, // unknown URLs
])
