import { useState } from "react" // download in-flight / error copy

import { downloadReportPdf } from "@/api/scores" // GET /reports/{id} → Blob
import { ApiError } from "@/api/types" // 404 / 503 detail
import { Button } from "@/components/ui/button" // thin control on the completed session page

// Candidate (or recruiter, if they ever share this page) download of the stored WeasyPrint PDF.
export function DownloadReportButton({ sessionId }: { sessionId: string }) {
  const [busy, setBusy] = useState(false) // disable while the blob is in flight
  const [error, setError] = useState<string | null>(null) // 404 score missing / 503 renderer / network

  async function onClick() {
    setBusy(true) // hide a double-click
    setError(null) // clear a previous failure
    try {
      const blob = await downloadReportPdf(sessionId) // owner-only; 404 not 403
      const url = URL.createObjectURL(blob) // temporary object URL for an <a download>
      const anchor = document.createElement("a") // not a visible nav link
      anchor.href = url // blob URL
      anchor.download = `interview-report-${sessionId}.pdf` // matches Content-Disposition basename
      anchor.rel = "noopener" // belt-and-suspenders for the synthetic click
      document.body.appendChild(anchor) // Firefox needs the node attached
      anchor.click() // start the browser download
      anchor.remove() // drop the node
      URL.revokeObjectURL(url) // do not leak blob URLs
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.detail) // FastAPI detail (score/report not found, renderer unavailable)
      } else {
        setError("could not download the report — is the API running?") // network
      }
    } finally {
      setBusy(false) // re-enable
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <Button type="button" onClick={() => void onClick()} disabled={busy}>
        {busy ? "Preparing report…" : "Download report"}
      </Button>
      {error !== null ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : (
        <p className="text-sm text-muted-foreground">
          PDF is built from the stored composite and attribution. Dual fluency is included when audio
          was transcribed; text-only answers do not invent fluency numbers.
        </p>
      )}
    </div>
  )
}
