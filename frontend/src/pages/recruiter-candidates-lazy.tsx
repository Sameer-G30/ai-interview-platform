import { lazy, Suspense } from "react" // route-level code splitting so Recharts stays out of the first-load bundle

// Recharts is only used on this page, so it becomes its own chunk loaded on first visit.
const RecruiterCandidatesPage = lazy(() =>
  import("@/pages/recruiter-candidates-page").then((module) => ({ default: module.RecruiterCandidatesPage })),
)

// Route element: shows a small placeholder while the chunk downloads.
export function RecruiterCandidatesLazy() {
  return (
    <Suspense fallback={<p className="p-6 text-sm text-muted-foreground">Loading...</p>}>
      <RecruiterCandidatesPage />
    </Suspense>
  )
}
