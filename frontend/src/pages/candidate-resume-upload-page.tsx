import { useState } from "react" // selected file, upload percent, API error
import { useMutation } from "@tanstack/react-query" // one-shot POST /resumes
import { Link, useNavigate } from "react-router-dom" // back to overview; push to results after 201

import { ApiError } from "@/api/types" // FastAPI detail for the error line
import { uploadResume } from "@/api/resumes" // multipart POST with XHR progress
import { ResumeDropzone } from "@/components/resume/resume-dropzone" // drag-drop + file picker
import { Button } from "@/components/ui/button" // submit; do not restyle the primitive
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card" // page chrome

// Candidate-only upload screen. After POST /resumes, navigates to the results page with ?job=.
export function CandidateResumeUploadPage() {
  const navigate = useNavigate() // results route needs resume_id + async_job_id
  const [file, setFile] = useState<File | null>(null) // null until a valid PDF is chosen
  const [percent, setPercent] = useState(0) // 0–100 from XHR; 100 ≠ parse complete
  const [error, setError] = useState<string | null>(null) // API or unexpected upload failure

  const upload = useMutation({
    mutationFn: (pdf: File) =>
      uploadResume(pdf, (next) => {
        setPercent(next) // live bar while bytes leave the browser
      }),
    onSuccess: (body) => {
      navigate(`/candidate/resume/${body.resume_id}?job=${body.async_job_id}`) // poll GET /jobs then GET /resumes
    },
    onError: (caught) => {
      if (caught instanceof ApiError) {
        setError(caught.detail) // FastAPI message (400/403/413/503/…)
        return // stay on this page
      }
      setError("could not upload — is the API running?") // network / unexpected
    },
  })

  const uploading = upload.isPending // freeze the dropzone while POST is in flight

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-6">
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-semibold">Upload resume</h1>
        <p className="text-muted-foreground">
          PDF only, 10 MiB max. Parsing runs on the ARQ worker — this page only uploads and enqueues.
        </p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Resume file</CardTitle>
          <CardDescription>Drag a PDF onto the box or use the file picker.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <ResumeDropzone
            disabled={uploading}
            error={error}
            file={file}
            onFile={(next) => {
              setError(null) // choosing a new file clears the last API error
              setPercent(0) // reset the bar
              setFile(next) // may be null if the dropzone rejected the file
            }}
          />
          {uploading ? (
            <div className="flex flex-col gap-1">
              <div className="h-2 overflow-hidden rounded-full bg-muted">
                <div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${percent}%` }} />
              </div>
              <p className="text-xs text-muted-foreground">Uploading… {percent}%</p>
            </div>
          ) : null}
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              disabled={file === null || uploading} // need a valid PDF and an idle mutation
              onClick={() => {
                if (file !== null) {
                  setError(null) // clear a previous API error before retrying
                  upload.mutate(file) // POST /resumes
                }
              }}
            >
              {uploading ? "Uploading…" : "Upload and parse"}
            </Button>
            <Button type="button" variant="outline" asChild>
              <Link to="/candidate">Back to overview</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
