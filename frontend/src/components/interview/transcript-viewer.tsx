import { useState } from "react" // selected word index for the timing detail row (mobile-friendly)

import type { WordTimestampOut } from "@/api/types" // speech_metrics.words
import type { ParsedSpeechMetrics, SpeechAnalysisState } from "@/lib/speech-metrics" // parsed payload + empty reasons
import { formatProbability, formatSeconds, formatWordClock } from "@/lib/speech-metrics" // display API timings only

// Copy for the cases where answers.transcript is still null. Do not invent a transcript string.
function emptyCopy(state: SpeechAnalysisState): string {
  if (state === "pending") {
    return "Transcription in progress. The full transcript and word timings appear when the worker finishes." // poller still open
  }
  if (state === "failed") {
    return "Transcription failed. You can re-upload the recording. No transcript was stored." // session is not abandoned
  }
  if (state === "stored") {
    return "Recording stored. Reload after the worker finishes to see the transcript, or re-upload to queue transcribe again." // no in-memory job id
  }
  if (state === "ready") {
    return "No transcript text or word timings on this row." // payload present but empty
  }
  return "No recording for this answer. A transcript needs audio; you can still score a typed answer." // text-only
}

// Tailwind class for Whisper probability: visual hint only, not a new score.
function probabilityClass(probability: number): string {
  if (probability < 0.5) {
    return "underline decoration-dotted text-muted-foreground" // low confidence
  }
  if (probability < 0.8) {
    return "text-foreground/80" // mid confidence
  }
  return "text-foreground" // high confidence
}

// Full-transcript viewer driven by answers.transcript plus speech_metrics.words (start/end/probability).
export function TranscriptViewer({
  transcript, // answers.transcript; null until transcribe succeeds
  metrics, // parsed speech_metrics; null when there is no payload
  state, // pending / failed / stored / text-only / ready
}: {
  transcript: string | null // plain ASR utterance
  metrics: ParsedSpeechMetrics | null // words live here, not in the transcript string
  state: SpeechAnalysisState // empty-state reason when there is nothing to show
}) {
  const words: WordTimestampOut[] = metrics?.words ?? [] // timed tokens; may be empty on a text-only row
  const fullText =
    typeof transcript === "string" && transcript.length > 0
      ? transcript
      : words.map((item) => item.word).join("").trim() // Whisper tokens often include a leading space
  const [selected, setSelected] = useState<number | null>(null) // tap a token to pin timings (hover is not enough on mobile)
  const selectedWord = selected !== null ? (words[selected] ?? null) : null // out-of-range -> null

  if (state !== "ready" || (fullText.length === 0 && words.length === 0)) {
    return (
      <div className="flex flex-col gap-2" data-testid="transcript-viewer">
        <p className="text-sm font-medium">Transcript</p>
        <p className="text-sm text-muted-foreground" data-testid="transcript-empty">
          {emptyCopy(state)}
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-3" data-testid="transcript-viewer">
      <p className="text-sm font-medium">Transcript</p>
      {metrics?.duration_s !== null && metrics?.duration_s !== undefined ? (
        <p className="text-xs text-muted-foreground">{formatSeconds(metrics.duration_s)} recording</p>
      ) : null}
      <p className="text-sm leading-relaxed" data-testid="transcript-text">
        {fullText}
      </p>
      {words.length > 0 ? (
        <div className="flex flex-col gap-2">
          <p className="text-xs text-muted-foreground">
            Word timings from speech_metrics.words. Tap a word for start/end and Whisper probability.
          </p>
          <p className="flex flex-wrap gap-1" data-testid="transcript-words">
            {words.map((item, index) => (
              <button
                key={`${item.start}-${item.end}-${index}`}
                type="button"
                data-testid="transcript-word"
                title={`${formatWordClock(item.start, item.end)} · ${formatProbability(item.probability)}`}
                className={`rounded-md px-1.5 py-0.5 text-sm tabular-nums hover:bg-muted ${probabilityClass(item.probability)} ${
                  selected === index ? "bg-muted ring-1 ring-border" : ""
                }`}
                onClick={() => {
                  setSelected((prev) => (prev === index ? null : index)) // toggle the same token off
                }}
              >
                {item.word.trim().length > 0 ? item.word.trim() : "·"}
              </button>
            ))}
          </p>
          {selectedWord !== null ? (
            <p className="text-xs text-muted-foreground" data-testid="transcript-word-detail">
              {selectedWord.word.trim() || "(space)"} · {formatWordClock(selectedWord.start, selectedWord.end)} ·{" "}
              {formatProbability(selectedWord.probability)}
              {metrics?.language ? ` · lang=${metrics.language}` : ""}
            </p>
          ) : null}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">No word timings on this row (transcript text only).</p>
      )}
    </div>
  )
}
