import type { AsyncJobStatus, FluencyMetricsOut, SpeechMetricsOut, WordTimestampOut } from "@/api/types" // GET /interviews speech JSON

// Empty-state reasons the transcript viewer and fluency panel share; never invent numbers for these.
export type SpeechAnalysisState = "ready" | "pending" | "failed" | "stored" | "text-only" // ready means the worker wrote payload

// UI-facing parse of answers.speech_metrics. Missing arms stay null so cards do not show guessed zeros.
export type ParsedSpeechMetrics = {
  words: WordTimestampOut[] // timed tokens for the transcript viewer
  language: string | null // "en" when Whisper was forced English
  duration_s: number | null // wav seconds; null if the worker omitted it
  fluency_transcript: FluencyMetricsOut | null // ASR word-gap arm; null if incomplete
  fluency_acoustic: FluencyMetricsOut | null // Silero VAD arm; null if incomplete
  prosody: SpeechMetricsOut["prosody"] | null // Praat pitch / intensity; null if incomplete
}

// Narrows one faster-whisper token; invalid entries are dropped rather than crashing the viewer.
function asWordTimestamp(raw: unknown): WordTimestampOut | null {
  if (typeof raw !== "object" || raw === null) {
    return null // not a word object
  }
  const record = raw as Record<string, unknown> // JSON object from speech_metrics.words
  if (typeof record.word !== "string") {
    return null // surface form is required
  }
  const start = asFiniteNumberOrNull(record.start) // seconds
  const end = asFiniteNumberOrNull(record.end) // seconds
  const probability = asFiniteNumberOrNull(record.probability) // 0–1
  if (start === null || end === null || probability === null) {
    return null // do not invent timings or confidence
  }
  return { word: record.word, start, end, probability } // UI-ready token
}

// Narrows one fluency arm. Missing headline fields -> null (do not render zeros as if they were measured).
export function asFluencyMetrics(raw: unknown): FluencyMetricsOut | null {
  if (typeof raw !== "object" || raw === null) {
    return null // arm omitted
  }
  const record = raw as Record<string, unknown> // fluency_transcript or fluency_acoustic
  const speech_rate_wpm = asFiniteNumberOrNull(record.speech_rate_wpm) // headline
  const articulation_rate_wpm = asFiniteNumberOrNull(record.articulation_rate_wpm) // headline
  const mean_pause_duration_s = asFiniteNumberOrNull(record.mean_pause_duration_s) // headline
  const pause_ratio = asFiniteNumberOrNull(record.pause_ratio) // headline
  const filler_rate = asFiniteNumberOrNull(record.filler_rate) // headline
  const filler_count = asFiniteNumberOrNull(record.filler_count) // headline count
  if (
    speech_rate_wpm === null ||
    articulation_rate_wpm === null ||
    mean_pause_duration_s === null ||
    pause_ratio === null ||
    filler_rate === null ||
    filler_count === null
  ) {
    return null // incomplete arm; empty UI rather than fake zeros
  }
  const word_count = asFiniteNumberOrNull(record.word_count) // supporting
  const total_duration_s = asFiniteNumberOrNull(record.total_duration_s) // supporting
  const speaking_duration_s = asFiniteNumberOrNull(record.speaking_duration_s) // supporting
  const pause_duration_s = asFiniteNumberOrNull(record.pause_duration_s) // supporting
  const pause_count = asFiniteNumberOrNull(record.pause_count) // supporting
  return {
    speech_rate_wpm, // words / total_duration * 60
    articulation_rate_wpm, // words / speaking_duration * 60
    mean_pause_duration_s, // mean pause length
    pause_ratio, // pause_duration / total_duration
    filler_rate, // filler_count / word_count
    filler_count, // integer count from the worker
    word_count: word_count ?? 0, // 0 only when the arm is otherwise valid
    total_duration_s: total_duration_s ?? 0, // clock for speech_rate
    speaking_duration_s: speaking_duration_s ?? 0, // clock for articulation_rate
    pause_duration_s: pause_duration_s ?? 0, // sum of pauses
    pause_count: pause_count ?? 0, // how many pauses passed the 200ms floor
  }
}

// Narrows GET /interviews speech_metrics; null until transcribe succeeds (or when text-only / failed).
export function asSpeechMetrics(raw: unknown): ParsedSpeechMetrics | null {
  if (typeof raw !== "object" || raw === null) {
    return null // column is JSON null
  }
  const record = raw as Record<string, unknown> // FastAPI JSON object
  const wordsRaw = record.words // expected list of word timestamps
  const words = Array.isArray(wordsRaw)
    ? wordsRaw.map(asWordTimestamp).filter((item): item is WordTimestampOut => item !== null) // drop junk
    : [] // missing words -> empty list so the viewer can still show transcript text
  return {
    words, // transcript viewer tokens
    language: typeof record.language === "string" ? record.language : null, // Whisper language tag
    duration_s: asFiniteNumberOrNull(record.duration_s), // wav seconds or null
    fluency_transcript: asFluencyMetrics(record.fluency_transcript), // ASR-gap arm
    fluency_acoustic: asFluencyMetrics(record.fluency_acoustic), // Silero arm
    prosody: asProsody(record.prosody), // Praat summaries or null
  }
}

// Pitch / intensity; null when the four Praat fields are not all finite numbers.
export function asProsody(raw: unknown): SpeechMetricsOut["prosody"] | null {
  if (typeof raw !== "object" || raw === null) {
    return null // prosody omitted
  }
  const record = raw as Record<string, unknown> // speech_metrics.prosody
  const pitch_mean_hz = asFiniteNumberOrNull(record.pitch_mean_hz) // F0 mean
  const pitch_std_hz = asFiniteNumberOrNull(record.pitch_std_hz) // F0 spread
  const intensity_mean_db = asFiniteNumberOrNull(record.intensity_mean_db) // loudness mean
  const intensity_std_db = asFiniteNumberOrNull(record.intensity_std_db) // loudness spread
  if (
    pitch_mean_hz === null ||
    pitch_std_hz === null ||
    intensity_mean_db === null ||
    intensity_std_db === null
  ) {
    return null // do not invent Praat numbers
  }
  return { pitch_mean_hz, pitch_std_hz, intensity_mean_db, intensity_std_db } // UI-ready
}

// Finite number or null — null means "do not display", never a guessed metric.
export function asFiniteNumberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null // reject NaN/Infinity
}

// True when this fluency arm has real headlines the cards may show.
export function hasRenderableFluency(raw: FluencyMetricsOut | null | undefined): raw is FluencyMetricsOut {
  if (raw === null || raw === undefined) {
    return false // missing arm
  }
  return (
    Number.isFinite(raw.speech_rate_wpm) &&
    Number.isFinite(raw.articulation_rate_wpm) &&
    Number.isFinite(raw.mean_pause_duration_s) &&
    Number.isFinite(raw.pause_ratio) &&
    Number.isFinite(raw.filler_rate) &&
    Number.isFinite(raw.filler_count)
  ) // incomplete objects are not renderable
}

// True when Praat fields are finite (zeros from unvoiced audio are real measurements).
export function hasRenderableProsody(raw: SpeechMetricsOut["prosody"] | null | undefined): boolean {
  if (raw === null || raw === undefined) {
    return false // omitted
  }
  return (
    Number.isFinite(raw.pitch_mean_hz) &&
    Number.isFinite(raw.pitch_std_hz) &&
    Number.isFinite(raw.intensity_mean_db) &&
    Number.isFinite(raw.intensity_std_db)
  ) // all four present
}

// Decide which empty/ready copy the analysis widgets should show. Does not invent metrics.
export function resolveSpeechAnalysisState(input: {
  hasAudio: boolean // GET session has_audio
  transcript: string | null // answers.transcript
  metrics: ParsedSpeechMetrics | null // parsed speech_metrics
  transcribeJobId: string | null // in-memory per-answer poller id
  transcribeStatus: AsyncJobStatus | undefined // GET /jobs/{id} status
}): SpeechAnalysisState {
  const hasTranscript = typeof input.transcript === "string" && input.transcript.length > 0 // non-empty ASR text
  const hasWords = input.metrics !== null && input.metrics.words.length > 0 // timed tokens
  const hasMetrics = input.metrics !== null // worker wrote the JSON column
  if (hasMetrics || hasTranscript || hasWords) {
    return "ready" // viewer + cards may render API values
  }
  if (input.transcribeStatus === "failed") {
    return "failed" // short async_jobs.error; session is not abandoned
  }
  if (input.transcribeStatus === "queued" || input.transcribeStatus === "running") {
    return "pending" // poller is still open
  }
  if (input.transcribeStatus === "succeeded" && !input.hasAudio) {
    return "text-only" // skip-succeed (no blob); not a fluency payload
  }
  if (input.transcribeStatus === "succeeded") {
    return "pending" // GET session refetch in flight
  }
  if (input.transcribeJobId !== null && input.transcribeStatus === undefined) {
    return "pending" // first poll not back yet
  }
  if (input.hasAudio) {
    return "stored" // blob on disk; reload or re-upload to poll
  }
  return "text-only" // typed answer, no recording
}

// Format helpers: display API numbers only. Callers must not pass guessed values.

export function formatWpm(value: number): string {
  return `${value.toFixed(1)} wpm` // one decimal; worker already computed this
}

export function formatSeconds(value: number): string {
  return `${value.toFixed(2)} s` // pause / duration
}

export function formatRatioPercent(value: number): string {
  return `${(value * 100).toFixed(0)}%` // pause_ratio and filler_rate are 0–1 fractions
}

export function formatHz(value: number): string {
  return `${value.toFixed(0)} Hz` // pitch
}

export function formatDb(value: number): string {
  return `${value.toFixed(1)} dB` // intensity
}

export function formatWordClock(start: number, end: number): string {
  return `${start.toFixed(2)}–${end.toFixed(2)} s` // token span on the wav
}

export function formatProbability(value: number): string {
  return `p=${value.toFixed(2)}` // Whisper per-word confidence
}
