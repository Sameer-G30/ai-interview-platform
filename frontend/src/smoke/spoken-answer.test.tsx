// Smoke test for the spoken-answer review state on the interview session page.
// One scored spoken answer and one unanswered question, rendered through the real route tree with a mocked fetch.
import { QueryClientProvider } from "@tanstack/react-query" // the session page and AuthProvider call useQuery
import { render, screen, waitFor, within } from "@testing-library/react" // render the real routes and query the DOM
import { ThemeProvider } from "next-themes" // the shell's theme toggle calls useTheme
import { createMemoryRouter, RouterProvider } from "react-router-dom" // in-memory history
import { afterEach, beforeEach, expect, test, vi } from "vitest" // the single frontend runner

import { buildAppRoutes } from "@/app/router" // the production route table, including the guards
import { clearTokens, setTokens } from "@/api/token-store" // same localStorage key the SPA uses
import type { InterviewSessionOut, UserOut } from "@/api/types" // JSON shapes the mock returns
import { TooltipProvider } from "@/components/ui/tooltip" // the sidebar tooltips require this provider
import { AuthProvider } from "@/lib/auth-provider" // GET /auth/me, then the guards read the user
import { createQueryClient } from "@/lib/query-client" // same defaults the SPA mounts

const SESSION_ID = "11111111-1111-4111-8111-111111111111" // path param for the page under test
const HEARD = "I would use a list when order matters and a set when I need fast membership checks." // transcript copy

const candidate: UserOut = {
  id: "00000000-0000-4000-8000-000000000001", // stable id
  email: "spoken@example.com", // sidebar display
  full_name: "Spoken Candidate", // sidebar display
  role: "candidate", // may open /candidate/*
  is_admin: false, // candidates are never admins
  is_active: true, // live account
}

// One fluency arm with every headline field the parser requires.
function arm(speechRate: number) {
  return {
    speech_rate_wpm: speechRate, // headline
    articulation_rate_wpm: 150, // headline
    mean_pause_duration_s: 0.4, // headline
    pause_ratio: 0.2, // headline
    filler_rate: 0.01, // headline
    filler_count: 1, // headline
    word_count: 16, // supporting
    total_duration_s: 8, // supporting
    speaking_duration_s: 6, // supporting
    pause_duration_s: 2, // supporting
    pause_count: 2, // supporting
  }
}

// Session fixture: row 0 is a scored spoken technical answer, row 1 is an unanswered behavioral question.
function sessionFixture(): InterviewSessionOut {
  const now = "2026-10-21T10:00:00Z" // fixed timestamp
  return {
    id: SESSION_ID,
    resume_id: "22222222-2222-4222-8222-222222222222",
    job_id: null, // practice
    status: "in_progress",
    started_at: now,
    completed_at: null,
    created_at: now,
    updated_at: now,
    answers: [
      {
        id: "a1",
        question_order: 0,
        question_text: "When would you use a list instead of a set?",
        question_kind: "technical",
        is_follow_up: false,
        answer_text: HEARD, // the transcript copy the judge read
        evaluation: { score: 4, rationale: "Clear trade-off.", strengths: ["accurate"], improvements: [] },
        has_audio: true,
        transcript: HEARD,
        speech_metrics: {
          words: [
            { word: "I", start: 0.0, end: 0.2, probability: 0.99 },
            { word: "would", start: 0.3, end: 0.6, probability: 0.97 },
          ],
          language: "en",
          duration_s: 8,
          fluency_transcript: arm(130),
          fluency_acoustic: arm(120),
          prosody: { pitch_mean_hz: 140, pitch_std_hz: 12, intensity_mean_db: 60, intensity_std_db: 5 },
        },
        created_at: now,
        updated_at: now,
      },
      {
        id: "a2",
        question_order: 1,
        question_text: "Tell me about a time you resolved a conflict.",
        question_kind: "behavioral",
        is_follow_up: false,
        answer_text: null, // not answered yet
        evaluation: null,
        has_audio: false,
        transcript: null,
        speech_metrics: null,
        created_at: now,
        updated_at: now,
      },
    ],
  } as unknown as InterviewSessionOut // speech_metrics is typed more narrowly than the JSON the API sends
}

// JSON response helper so the mock looks like FastAPI.
function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })
}

// Stand-in for the Vite proxy: only the two routes this page touches.
function mockFetch(input: RequestInfo | URL): Promise<Response> {
  const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url // fetch input shapes
  const path = new URL(raw, "http://localhost").pathname // "/interviews/<id>"
  if (path === "/auth/me") {
    return Promise.resolve(jsonResponse(200, candidate))
  }
  if (path === `/interviews/${SESSION_ID}`) {
    return Promise.resolve(jsonResponse(200, sessionFixture()))
  }
  return Promise.resolve(jsonResponse(404, { detail: `smoke mock has no ${path}` })) // fail visibly
}

beforeEach(() => {
  localStorage.clear() // drop a previous test's token payload
  clearTokens() // module copy is separate from localStorage until this runs
  setTokens({ accessToken: "smoke-access", refreshToken: "smoke-refresh" }) // signed in as the candidate
  vi.stubGlobal("fetch", vi.fn(mockFetch)) // every apiFetch hits the mock
  // jsdom has no MediaRecorder; claim Opus/WebM support so the recorder renders its controls instead of the
  // "needs Chromium" message. Nothing is recorded in these tests.
  vi.stubGlobal("MediaRecorder", class { static isTypeSupported = () => true })
})

afterEach(() => {
  vi.unstubAllGlobals() // restore fetch for later files
  clearTokens() // unmounted provider must not keep a session
})

function renderSession() {
  const memoryRouter = createMemoryRouter(buildAppRoutes(), { initialEntries: [`/candidate/interview/${SESSION_ID}`] })
  render(
    <ThemeProvider attribute="class" defaultTheme="light" enableSystem={false}>
      <QueryClientProvider client={createQueryClient()}>
        <TooltipProvider>
          <AuthProvider>
            <RouterProvider router={memoryRouter} />
          </AuthProvider>
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>,
  )
  return memoryRouter
}

test("a scored spoken answer shows What we heard, word timings, both fluency arms, and no text box", async () => {
  renderSession() // lands on the first open question after load
  // The first open question is the unanswered one (index 1); step back to the scored spoken answer.
  await screen.findByText("Tell me about a time you resolved a conflict.")
  const previous = await screen.findByTestId("prev-question")
  previous.click() // move to row 0

  const heard = await screen.findByTestId("answer-text") // the "What we heard" transcript copy
  expect(heard).toHaveTextContent(HEARD)
  expect(screen.getByText("What we heard")).toBeInTheDocument() // heading for that block
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument() // answers are spoken: no text input
  expect(screen.getByTestId("evaluation-score")).toHaveTextContent("4 / 5") // judge score is visible
  await waitFor(() => {
    expect(screen.getAllByTestId("transcript-word").length).toBeGreaterThan(0) // word timings render
  })
  const panel = screen.getByTestId("fluency-panel")
  expect(within(panel).getByTestId("fluency-transcript")).toBeInTheDocument() // transcript arm
  expect(within(panel).getByTestId("fluency-acoustic")).toBeInTheDocument() // acoustic arm
})

test("an unanswered question says recording is required and offers no typed answer", async () => {
  renderSession() // the first open question is the behavioral one
  expect(await screen.findByText("Tell me about a time you resolved a conflict.")).toBeInTheDocument()
  expect(screen.getByTestId("record-required")).toHaveTextContent("Recording is required") // required copy
  expect(screen.getByTestId("record-start")).toBeInTheDocument() // the recorder is the only input
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument() // no textarea
  expect(screen.queryByTestId("answer-text")).not.toBeInTheDocument() // nothing heard yet
  expect(screen.getByTestId("progress-steps")).toHaveTextContent("Recording") // progress line starts at Recording
})
