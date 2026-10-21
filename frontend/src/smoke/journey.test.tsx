// Smoke tests for the live route tree: login lands on the role home, and the existing guards hold.
// jsdom plus a mocked fetch. No Playwright, and no page components were rewritten for this file.
import { QueryClientProvider } from "@tanstack/react-query" // AuthProvider and the dashboards call useQuery
import { render, screen, waitFor } from "@testing-library/react" // render the real routes and find headings
import userEvent from "@testing-library/user-event" // types into the login form the way a user would
import { ThemeProvider } from "next-themes" // the sidebar theme toggle calls useTheme
import { createMemoryRouter, RouterProvider } from "react-router-dom" // in-memory history; no browser navigation
import { afterEach, beforeEach, expect, test, vi } from "vitest" // the single frontend runner

import type { UserOut } from "@/api/types" // GET /auth/me JSON shape the mock returns
import { clearTokens, setTokens } from "@/api/token-store" // same localStorage key the SPA uses
import { TooltipProvider } from "@/components/ui/tooltip" // the sidebar tooltips require this provider
import { buildAppRoutes } from "@/app/router" // the production route table, including the guards
import { AuthProvider } from "@/lib/auth-provider" // login() then GET /auth/me, then the guards read the user
import { createQueryClient } from "@/lib/query-client" // same defaults the SPA mounts

// Mutable "server" user. The fetch mock reads this when the form posts /auth/login and when /auth/me runs.
let sessionUser: UserOut = candidateUser() // default; each test assigns the persona it is signing in

// A candidate fixture. is_admin stays false; registration and this mock never invent an admin role.
function candidateUser(): UserOut {
  return {
    id: "00000000-0000-4000-8000-000000000001", // stable id so the admin page can tell "self" apart
    email: "smoke-candidate@example.com", // typed into the login form in the candidate test
    full_name: "Smoke Candidate", // sidebar display name; not asserted
    role: "candidate", // the only role that may open /candidate
    is_admin: false, // candidates cannot be admins
    is_active: true, // an inactive account would not get this far in the real API
  }
}

// A recruiter without the admin flag. home is still /recruiter.
function recruiterUser(): UserOut {
  return {
    id: "00000000-0000-4000-8000-000000000002", // distinct from the candidate fixture
    email: "smoke-recruiter@example.com", // typed into the recruiter login test
    full_name: "Smoke Recruiter", // sidebar display name
    role: "recruiter", // /candidate must bounce this user home
    is_admin: false, // Admin nav and /admin stay closed
    is_active: true, // live account
  }
}

// An is_admin recruiter. The home path is still /recruiter; /admin is an extra route.
function adminUser(): UserOut {
  return {
    id: "00000000-0000-4000-8000-000000000003", // distinct from the other two fixtures
    email: "smoke-admin@example.com", // typed into the admin login test
    full_name: "Smoke Admin", // sidebar display name
    role: "recruiter", // not a third role value
    is_admin: true, // the flag that opens /admin
    is_active: true, // live account
  }
}

// JSON response helper so each branch of the mock looks like FastAPI.
function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status, // HTTP status the client turns into ApiError or parsed JSON
    headers: { "Content-Type": "application/json" }, // apiFetch always parses JSON
  })
}

// Pathname of a fetch() URL, whether the caller passed a relative path or an absolute one.
function requestPath(input: RequestInfo | URL): string {
  const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url // fetch's three input shapes
  return new URL(raw, "http://localhost").pathname // "/auth/login" stays "/auth/login"
}

// Stand-in for the Vite proxy. Only the routes the smoke journey touches are implemented.
function mockFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const path = requestPath(input) // which API path the SPA asked for
  const method = (init?.method ?? "GET").toUpperCase() // apiFetch always sets a method
  if (method === "POST" && path === "/auth/login") {
    return Promise.resolve(
      jsonResponse(200, {
        access_token: "smoke-access", // not a real JWT; the mock /auth/me does not verify it
        refresh_token: "smoke-refresh", // opaque string, matching the real client contract
        token_type: "bearer", // TokenPairResponse field the client ignores beyond storage
      }),
    )
  }
  if (method === "GET" && path === "/auth/me") {
    return Promise.resolve(jsonResponse(200, sessionUser)) // whoever the test selected
  }
  if (method === "POST" && path === "/auth/logout") {
    return Promise.resolve(new Response(null, { status: 204 })) // logout is No Content
  }
  if (method === "GET" && path === "/interviews") {
    return Promise.resolve(jsonResponse(200, [])) // empty candidate history; the dashboard still renders
  }
  if (method === "GET" && path === "/matches") {
    return Promise.resolve(jsonResponse(404, { detail: "no parsed resume" })) // the dashboard's empty state
  }
  if (method === "GET" && path.startsWith("/admin/users")) {
    return Promise.resolve(jsonResponse(200, [])) // admin Users tab empty state
  }
  return Promise.resolve(jsonResponse(404, { detail: `smoke mock has no ${method} ${path}` })) // fail visibly
}

// Mount the same providers as App.tsx, but with a memory router so each test picks its start URL.
function renderAt(path: string) {
  const queryClient = createQueryClient() // one cache per test render
  const memoryRouter = createMemoryRouter(buildAppRoutes(), { initialEntries: [path] }) // start URL
  render(
    <ThemeProvider attribute="class" defaultTheme="light" enableSystem={false}>
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <AuthProvider>
            <RouterProvider router={memoryRouter} />
          </AuthProvider>
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>,
  )
  return memoryRouter // the test navigates this to hit a guard
}

// After a guard redirect, query the heading inside waitFor so the assertion sees the page that stuck.
async function expectHome(
  memoryRouter: { state: { location: { pathname: string } } }, // the memory router from renderAt
  path: string, // the URL the guard should settle on
  heading: string, // the h1 on that page
): Promise<void> {
  await waitFor(() => {
    expect(memoryRouter.state.location.pathname).toBe(path) // redirect finished
    expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument() // page mounted
  })
}

// Fill the real login form and wait until login() has stored the mock session.
async function signIn(email: string): Promise<void> {
  const user = userEvent.setup() // pointer and keyboard events
  await user.type(screen.getByLabelText("Email"), email) // RHF field wired to the Email label
  await user.type(screen.getByLabelText("Password"), "smoke-pass") // any non-empty password passes the Zod schema
  await user.click(screen.getByRole("button", { name: "Sign in" })) // POST /auth/login then GET /auth/me
}

beforeEach(() => {
  localStorage.clear() // drop a previous test's aiip.auth.tokens payload
  clearTokens() // the module-level copy is not the same object as localStorage until this runs
  sessionUser = candidateUser() // a test that needs another persona assigns it before render or click
  vi.stubGlobal("fetch", vi.fn(mockFetch)) // every apiFetch in this test hits the mock
})

afterEach(() => {
  vi.unstubAllGlobals() // put fetch back so a later file cannot see this mock
  clearTokens() // subscribers from the unmounted provider must not keep a session
})

test("a guest opening / is sent to the login form", async () => {
  renderAt("/") // RoleLanding with no tokens
  expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument() // login page, not a dashboard
})

test("an unauthenticated visit to /candidate is sent to login", async () => {
  renderAt("/candidate") // RequireAuth has no tokens
  expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument() // bounced before the dashboard
})

test("login as a candidate lands on the candidate dashboard", async () => {
  sessionUser = candidateUser() // /auth/me returns this candidate
  const memoryRouter = renderAt("/login") // guest form
  await signIn(sessionUser.email) // POST /auth/login, then the provider loads /auth/me
  expect(await screen.findByRole("heading", { name: "Candidate dashboard" })).toBeInTheDocument() // role home
  await waitFor(() => {
    expect(memoryRouter.state.location.pathname).toBe("/candidate") // homePathForUser, not /admin
  })
})

test("login as a recruiter lands on recruiter home without Interview or Admin", async () => {
  sessionUser = recruiterUser() // recruiter, is_admin false
  const memoryRouter = renderAt("/login") // guest form
  await signIn(sessionUser.email) // same login form both roles use
  expect(await screen.findByRole("heading", { name: "Recruiter home" })).toBeInTheDocument() // role home
  await waitFor(() => {
    expect(memoryRouter.state.location.pathname).toBe("/recruiter") // admins would land here too
  })
  expect(screen.queryByRole("link", { name: "Interview" })).not.toBeInTheDocument() // recruiter has no Interview screen
  expect(screen.queryByTestId("admin-nav-link")).not.toBeInTheDocument() // flag is off, so Admin stays hidden
})

test("an is_admin recruiter still lands on /recruiter and can open /admin", async () => {
  sessionUser = adminUser() // recruiter plus the flag
  const memoryRouter = renderAt("/login") // guest form
  await signIn(sessionUser.email) // login does not grow a third role home
  expect(await screen.findByRole("heading", { name: "Recruiter home" })).toBeInTheDocument() // same home as a plain recruiter
  expect(screen.getByText(/admin flag on/)).toBeInTheDocument() // the home copy mentions the flag
  expect(screen.getByTestId("admin-nav-link")).toBeInTheDocument() // Admin nav is visible only for this flag
  await memoryRouter.navigate("/admin") // extra route, not the post-login landing
  expect(await screen.findByRole("heading", { name: "Admin" })).toBeInTheDocument() // RequireAdmin allowed it
  expect(await screen.findByText("No users match these filters.")).toBeInTheDocument() // GET /admin/users returned []
})

test("a candidate who opens /recruiter is sent back to the candidate dashboard", async () => {
  sessionUser = candidateUser() // wrong role for /recruiter
  const memoryRouter = renderAt("/login") // sign in first so RequireAuth is satisfied
  await signIn(sessionUser.email) // now a candidate session exists
  await screen.findByRole("heading", { name: "Candidate dashboard" }) // wait until the user is loaded
  await memoryRouter.navigate("/recruiter") // RequireRole rejects this role
  await expectHome(memoryRouter, "/candidate", "Candidate dashboard") // bounced to the candidate home
})

test("a recruiter who opens /candidate is sent back to recruiter home", async () => {
  sessionUser = recruiterUser() // wrong role for /candidate
  const memoryRouter = renderAt("/login") // sign in first
  await signIn(sessionUser.email) // recruiter session
  await screen.findByRole("heading", { name: "Recruiter home" }) // user is loaded
  await memoryRouter.navigate("/candidate") // RequireRole rejects this role
  await expectHome(memoryRouter, "/recruiter", "Recruiter home") // bounced to the recruiter home
})

test("a recruiter without the admin flag is sent home from /admin", async () => {
  sessionUser = recruiterUser() // is_admin false
  const memoryRouter = renderAt("/login") // sign in first; /admin also sits under RequireAuth
  await signIn(sessionUser.email) // recruiter session
  await screen.findByRole("heading", { name: "Recruiter home" }) // user is loaded
  await memoryRouter.navigate("/admin") // RequireAdmin rejects the missing flag
  await expectHome(memoryRouter, "/recruiter", "Recruiter home") // homePathForUser, not the ops page
  expect(screen.queryByRole("heading", { name: "Admin" })).not.toBeInTheDocument() // the ops page did not mount
})

test("a signed-in candidate who opens /login is sent to the candidate dashboard", async () => {
  sessionUser = candidateUser() // /auth/me will restore this user from the stored token
  setTokens({ accessToken: "smoke-access", refreshToken: "smoke-refresh" }) // localStorage key aiip.auth.tokens
  const memoryRouter = renderAt("/login") // RequireGuest must not show the form
  expect(await screen.findByRole("heading", { name: "Candidate dashboard" })).toBeInTheDocument() // role home
  await waitFor(() => {
    expect(memoryRouter.state.location.pathname).toBe("/candidate") // login was skipped
  })
})
