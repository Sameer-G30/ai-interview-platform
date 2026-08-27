import { useEffect, useRef, useState } from "react" // recorder lifecycle, analyser rAF, upload progress

import { AUDIO_MIME, MAX_AUDIO_BYTES, uploadAnswerAudio } from "@/api/interviews" // Chromium webm/opus + 10 MiB cap
import { ApiError } from "@/api/types" // FastAPI detail for upload failures
import { Button } from "@/components/ui/button" // record / stop / upload / retry; do not restyle the primitive

// Permission / capability states the candidate can actually recover from (Chromium-first; no Safari promise).
type RecorderGate = "ready" | "unsupported" | "denied" | "unavailable" // ready means getUserMedia can be called

// Props: parent owns session/answer ids so a question change tears this down and remounts via `key`.
type AudioRecorderProps = {
  sessionId: string // POST .../audio path param
  answerId: string // POST .../audio path param
  hasAudio: boolean // from GET session has_audio; true after a successful upload (or a previous visit)
  disabled?: boolean // true while text evaluate is in flight or the session is abandoned
  onUploaded: () => void // parent refetches the session so has_audio flips without a second poller
}

// True when this browser claims MediaRecorder + the Opus/WebM mime the backend accepts.
function isOpusWebmSupported(): boolean {
  if (typeof MediaRecorder === "undefined") {
    return false // Safari / missing API
  }
  if (typeof MediaRecorder.isTypeSupported !== "function") {
    return false // ancient engine; we still refuse rather than guess a codec
  }
  return MediaRecorder.isTypeSupported(AUDIO_MIME) // "audio/webm;codecs=opus"
}

// RMS of an AnalyserNode time-domain buffer, 0–1, used for the level meter.
function rmsFromTimeDomain(bytes: Uint8Array): number {
  let sum = 0 // sum of squared centered samples
  for (let i = 0; i < bytes.length; i += 1) {
    const centered = (bytes[i] - 128) / 128 // 0–255 mid-line 128 → roughly -1..1
    sum += centered * centered // energy
  }
  return Math.sqrt(sum / Math.max(bytes.length, 1)) // 0–1
}

// Chromium MediaRecorder capture: permission, waveform + level, upload with progress, retry/overwrite.
export function AudioRecorder({ sessionId, answerId, hasAudio, disabled = false, onUploaded }: AudioRecorderProps) {
  const [gate, setGate] = useState<RecorderGate>(() => (isOpusWebmSupported() ? "ready" : "unsupported")) // compute once
  const [recording, setRecording] = useState(false) // true between start() and onstop
  const [blob, setBlob] = useState<Blob | null>(null) // last take; null until Stop
  const [level, setLevel] = useState(0) // 0–1 RMS while recording
  const [percent, setPercent] = useState(0) // 0–100 XHR progress; 100 ≠ Whisper
  const [uploading, setUploading] = useState(false) // freeze buttons while POST is in flight
  const [error, setError] = useState<string | null>(null) // permission / size / API errors
  const [uploadedHere, setUploadedHere] = useState(false) // local success so retry copy can change before refetch

  const mediaRef = useRef<MediaRecorder | null>(null) // active recorder, stopped on unmount
  const streamRef = useRef<MediaStream | null>(null) // mic tracks to stop after recording
  const chunksRef = useRef<BlobPart[]>([]) // MediaRecorder dataavailable pieces
  const audioCtxRef = useRef<AudioContext | null>(null) // analyser graph; closed on stop
  const analyserRef = useRef<AnalyserNode | null>(null) // time-domain source for waveform + level
  const rafRef = useRef<number>(0) // requestAnimationFrame id for the meter loop
  const canvasRef = useRef<HTMLCanvasElement | null>(null) // waveform canvas
  const mountedRef = useRef(true) // avoid setState after unmount
  const stopCaptureRef = useRef<() => void>(() => {}) // latest stopCapture for the unmount cleanup

  function stopCapture(): void {
    if (rafRef.current !== 0) {
      cancelAnimationFrame(rafRef.current) // stop the meter loop
      rafRef.current = 0 // so a second stop is a no-op
    }
    const recorder = mediaRef.current // may already be inactive
    if (recorder !== null && recorder.state !== "inactive") {
      recorder.stop() // flushes the last dataavailable; onstop builds the blob
    }
    mediaRef.current = null // drop the handle
    const stream = streamRef.current // mic tracks
    if (stream !== null) {
      for (const track of stream.getTracks()) {
        track.stop() // release the permission indicator
      }
    }
    streamRef.current = null // drop the stream
    const ctx = audioCtxRef.current // Web Audio graph
    if (ctx !== null) {
      void ctx.close() // ignore the promise; unmount cannot await
    }
    audioCtxRef.current = null // drop the context
    analyserRef.current = null // drop the analyser
  }

  stopCaptureRef.current = stopCapture // always the latest closure; unmount reads the ref

  useEffect(() => {
    mountedRef.current = true // this instance is alive
    return () => {
      mountedRef.current = false // skip setState in late MediaRecorder callbacks
      stopCaptureRef.current() // release the mic if the candidate navigates away mid-take
    }
  }, [])

  function drawWaveform(bytes: Uint8Array): void {
    const canvas = canvasRef.current // may be unmounted
    if (canvas === null) {
      return // nothing to paint
    }
    const ctx = canvas.getContext("2d") // 2d is enough for a line
    if (ctx === null) {
      return // canvas unavailable
    }
    const width = canvas.width // device pixels
    const height = canvas.height // device pixels
    ctx.clearRect(0, 0, width, height) // wipe the previous frame
    ctx.strokeStyle = "currentColor" // follow the theme foreground as best we can
    ctx.lineWidth = 2 // visible on a 48px canvas
    ctx.beginPath() // one polyline
    const step = Math.max(1, Math.floor(bytes.length / width)) // subsample so we draw one point per x
    for (let x = 0; x < width; x += 1) {
      const sample = bytes[x * step] ?? 128 // 0–255
      const y = (sample / 255) * height // map to canvas y
      if (x === 0) {
        ctx.moveTo(x, y) // start
      } else {
        ctx.lineTo(x, y) // continue
      }
    }
    ctx.stroke() // paint
  }

  function tickMeter(): void {
    const analyser = analyserRef.current // set in startRecording
    if (analyser === null) {
      return // stopCapture already ran
    }
    const bytes = new Uint8Array(analyser.fftSize) // time-domain buffer
    analyser.getByteTimeDomainData(bytes) // fill
    if (mountedRef.current) {
      setLevel(rmsFromTimeDomain(bytes)) // level bar
      drawWaveform(bytes) // canvas
    }
    rafRef.current = requestAnimationFrame(tickMeter) // loop until stopCapture cancels
  }

  async function startRecording(): Promise<void> {
    setError(null) // clear a previous permission/upload error
    setBlob(null) // discard a prior take so Stop creates a fresh blob
    setUploadedHere(false) // a new take is not yet uploaded
    chunksRef.current = [] // reset pieces
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true }) // Chromium permission prompt
      if (!mountedRef.current) {
        for (const track of stream.getTracks()) {
          track.stop() // unmounted during the prompt
        }
        return // do not start a recorder nobody will stop
      }
      streamRef.current = stream // kept so stopCapture can release tracks
      const audioCtx = new AudioContext() // analyser graph
      audioCtxRef.current = audioCtx // closed on stop
      const source = audioCtx.createMediaStreamSource(stream) // mic → analyser
      const analyser = audioCtx.createAnalyser() // time-domain
      analyser.fftSize = 2048 // enough points for a short waveform
      source.connect(analyser) // no destination: we do not play the mic back
      analyserRef.current = analyser // tickMeter reads this
      const recorder = new MediaRecorder(stream, { mimeType: AUDIO_MIME }) // audio/webm;codecs=opus
      recorder.ondataavailable = (event: BlobEvent) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data) // accumulate slices
        }
      }
      recorder.onstop = () => {
        const take = new Blob(chunksRef.current, { type: "audio/webm" }) // backend allow-list is audio/webm
        if (mountedRef.current) {
          setBlob(take) // ready to upload or discard
          setRecording(false) // Stop finished
          setLevel(0) // reset the meter
        }
      }
      mediaRef.current = recorder // stopCapture will call stop()
      recorder.start() // begin capturing
      setGate("ready") // permission succeeded
      setRecording(true) // UI: Stop is enabled
      tickMeter() // start waveform/level
    } catch (caught) {
      const name = caught instanceof DOMException ? caught.name : "" // NotAllowedError / NotFoundError / ...
      if (name === "NotAllowedError" || name === "PermissionDeniedError") {
        setGate("denied") // mic blocked
        setError("Microphone permission was denied. Type an answer instead, or allow the mic and retry.")
        return // stay on this question
      }
      if (name === "NotFoundError") {
        setGate("unavailable") // no input device
        setError("No microphone was found. You can still type an answer.")
        return // stay on this question
      }
      setError("Could not start the recorder. Chromium is required; Safari is not supported.") // generic
    }
  }

  async function uploadTake(): Promise<void> {
    if (blob === null) {
      return // nothing to send
    }
    if (blob.size > MAX_AUDIO_BYTES) {
      setError("Recording is larger than the 10 MiB limit. Record a shorter take.") // matches API 400
      return // do not POST
    }
    if (blob.size === 0) {
      setError("That recording is empty. Record again.") // matches API empty rejection
      return // do not POST
    }
    setError(null) // clear a previous API error before retry
    setUploading(true) // freeze the button
    setPercent(0) // reset the bar
    try {
      const file = new File([blob], "answer.webm", { type: "audio/webm" }) // field name is applied in uploadAnswerAudio
      await uploadAnswerAudio(sessionId, answerId, file, (next) => {
        if (mountedRef.current) {
          setPercent(next) // live bar while bytes leave the browser
        }
      })
      if (mountedRef.current) {
        setUploadedHere(true) // local success copy
        setUploading(false) // unfreeze
        onUploaded() // parent GET /interviews/{id} so has_audio is true
      }
    } catch (caught) {
      if (!mountedRef.current) {
        return // unmounted during POST
      }
      setUploading(false) // unfreeze so Retry works
      if (caught instanceof ApiError) {
        setError(caught.detail) // FastAPI 400/404/409/429
        return // stay on this take
      }
      setError("could not upload audio — is the API running?") // network
    }
  }

  if (gate === "unsupported") {
    return (
      <p className="text-sm text-muted-foreground">
        Audio capture needs Chromium (Chrome or Edge) with <code>audio/webm;codecs=opus</code>. You can still type an
        answer. Safari is not supported this phase.
      </p>
    )
  }

  const stored = hasAudio || uploadedHere // GET flag or a success in this mount
  const canRecord = !disabled && !recording && !uploading && gate === "ready" // Start is idle
  const canStop = recording && !disabled // Stop ends the take
  const canUpload = blob !== null && !recording && !uploading && !disabled // Upload / Retry

  return (
    <div className="flex flex-col gap-3">
      <p className="text-xs text-muted-foreground">
        Optional recording for later transcription. Submitting text is what scores the answer. Target Chromium; capture
        is <code>audio/webm;codecs=opus</code>.
      </p>
      <canvas
        ref={canvasRef}
        width={320}
        height={48}
        className="h-12 w-full rounded-md border border-border bg-muted/40 text-primary"
        aria-hidden="true"
      />
      <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        <div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${Math.round(level * 100)}%` }} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!canRecord}
          data-testid="record-start"
          onClick={() => {
            void startRecording() // permission prompt
          }}
        >
          {recording ? "Recording…" : stored ? "Record again" : "Start recording"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!canStop}
          data-testid="record-stop"
          onClick={() => {
            stopCapture() // builds the blob in onstop
          }}
        >
          Stop
        </Button>
        <Button
          type="button"
          size="sm"
          disabled={!canUpload}
          data-testid="upload-audio"
          onClick={() => {
            void uploadTake() // POST multipart; retry overwrites audio_path
          }}
        >
          {uploading ? `Uploading… ${percent}%` : stored ? "Re-upload" : "Upload recording"}
        </Button>
      </div>
      {stored ? <p className="text-xs text-muted-foreground">Recording stored. You can re-record and upload again.</p> : null}
      {error !== null ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      {gate === "denied" ? (
        <p className="text-sm text-muted-foreground">
          Allow the microphone in the browser site settings, then click Start recording again.
        </p>
      ) : null}
    </div>
  )
}
