import { useCallback, useId, useRef, useState } from "react" // refs for the hidden input; local drag/error state

import { UploadIcon } from "lucide-react" // upload glyph inside the drop target

import { isPdfFile, MAX_RESUME_BYTES, RESUME_ACCEPT } from "@/api/resumes" // PDF + 10 MiB checks matching the API
import { cn } from "@/lib/utils" // merges Tailwind classes for the drag-over ring

// Props for the dropzone: the parent owns the selected file so the upload page can show progress.
type ResumeDropzoneProps = {
  disabled?: boolean // true while POST /resumes is in flight
  error?: string | null // validation or API error shown under the drop target
  file: File | null // currently chosen PDF, or null when empty
  onFile: (file: File | null) => void // parent stores the file and clears prior errors
}

// Human-readable size for the selected-file line (bytes -> KiB/MiB).
function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B` // tiny files; should not happen for a real PDF
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KiB` // typical one-page resume
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB` // still under the 10 MiB cap
}

// Drag-and-drop PDF picker with a hidden <input type="file"> fallback.
export function ResumeDropzone({ disabled = false, error = null, file, onFile }: ResumeDropzoneProps) {
  const inputId = useId() // stable id so the label/button can target the hidden input
  const inputRef = useRef<HTMLInputElement>(null) // programmatic click from the drop target
  const [dragOver, setDragOver] = useState(false) // visual highlight while a file is dragged over the box
  const [localError, setLocalError] = useState<string | null>(null) // client-side type/size errors

  const shownError = error ?? localError // parent API errors win over local validation copy

  const acceptFile = useCallback(
    (next: File | null) => {
      setLocalError(null) // clear the previous client-side message
      if (next === null) {
        onFile(null) // parent clears the selection
        return // nothing else to validate
      }
      if (!isPdfFile(next)) {
        setLocalError("Only PDF files are accepted.") // matches the API content-type rule
        onFile(null) // do not keep a rejected file
        return // stop
      }
      if (next.size > MAX_RESUME_BYTES) {
        setLocalError("File is larger than the 10 MiB limit.") // matches backend _MAX_UPLOAD_BYTES
        onFile(null) // do not keep an oversized file
        return // stop
      }
      if (next.size === 0) {
        setLocalError("That PDF is empty.") // API also rejects empty uploads
        onFile(null) // do not keep an empty file
        return // stop
      }
      onFile(next) // parent may now POST /resumes
    },
    [onFile], // recreate only if the parent callback identity changes
  )

  return (
    <div className="flex flex-col gap-2">
      <input
        ref={inputRef}
        id={inputId}
        type="file"
        accept={RESUME_ACCEPT}
        className="sr-only"
        disabled={disabled}
        onChange={(event) => {
          const chosen = event.target.files?.[0] ?? null // file-picker fallback
          acceptFile(chosen) // run the same PDF/size checks as drop
          event.target.value = "" // allow picking the same file again after a rejection
        }}
      />
      <div
        role="button"
        tabIndex={disabled ? -1 : 0}
        aria-disabled={disabled}
        aria-describedby={shownError ? `${inputId}-error` : undefined}
        onClick={() => {
          if (!disabled) {
            inputRef.current?.click() // open the native file picker
          }
        }}
        onKeyDown={(event) => {
          if (disabled) {
            return // ignore keyboard while uploading
          }
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault() // do not scroll on Space
            inputRef.current?.click() // same as click
          }
        }}
        onDragEnter={(event) => {
          event.preventDefault() // allow drop
          if (!disabled) {
            setDragOver(true) // highlight the box
          }
        }}
        onDragOver={(event) => {
          event.preventDefault() // required for onDrop to fire
        }}
        onDragLeave={(event) => {
          event.preventDefault() // keep the page from navigating
          setDragOver(false) // remove the highlight
        }}
        onDrop={(event) => {
          event.preventDefault() // do not open the PDF in a new tab
          setDragOver(false) // drop finished
          if (disabled) {
            return // ignore drops while POST is in flight
          }
          const dropped = event.dataTransfer.files[0] ?? null // first file only
          acceptFile(dropped) // PDF + size checks
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-muted/30 px-4 py-10 text-center outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
          dragOver ? "border-primary bg-muted/60" : null, // stronger ring while dragging
          disabled ? "pointer-events-none opacity-50" : null, // freeze during upload
        )}
      >
        <UploadIcon className="size-8 text-muted-foreground" />
        <p className="text-sm font-medium">Drop a PDF resume here</p>
        <p className="text-xs text-muted-foreground">or click to choose a file · PDF only · max 10 MiB</p>
        {file !== null ? (
          <p className="text-xs text-foreground">
            {file.name} · {formatBytes(file.size)}
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">No file selected.</p>
        )}
      </div>
      {shownError ? (
        <p id={`${inputId}-error`} className="text-sm text-destructive" role="alert">
          {shownError}
        </p>
      ) : null}
    </div>
  )
}
