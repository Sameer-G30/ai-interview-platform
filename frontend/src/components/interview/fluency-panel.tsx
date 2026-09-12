import type { FluencyMetricsOut } from "@/api/types" // one fluency arm from speech_metrics
import type { ParsedSpeechMetrics, SpeechAnalysisState } from "@/lib/speech-metrics" // parsed payload + empty reasons
import {
  formatDb,
  formatHz,
  formatRatioPercent,
  formatSeconds,
  formatWpm,
  hasRenderableFluency,
  hasRenderableProsody,
} from "@/lib/speech-metrics" // format API numbers only; never guess

// Copy when speech_metrics is null. Zeros are not shown in these states.
function emptyCopy(state: SpeechAnalysisState): string {
  if (state === "pending") {
    return "Fluency cards appear after transcription succeeds. No placeholder rates are shown while the job runs." // do not show 0 wpm
  }
  if (state === "failed") {
    return "Transcription failed, so there are no fluency or prosody numbers for this answer." // worker left speech_metrics null
  }
  if (state === "stored") {
    return "Recording stored. Fluency metrics are empty until the transcribe worker writes speech_metrics." // reload or re-upload
  }
  if (state === "ready") {
    return "This answer has no renderable fluency or prosody fields. Numbers are not guessed in the browser." // incomplete JSON
  }
  return "No audio on this answer, so there are no fluency metrics. Typed answers are scored from text only." // text-only
}

// One headline metric; `value` is already formatted from an API field.
function MetricCard({
  label, // short name
  value, // formatted API number
  hint, // supporting clock / count
}: {
  label: string // card title
  value: string // e.g. "120.0 wpm"
  hint?: string // e.g. "3 fillers"
}) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-medium tabular-nums">{value}</p>
      {hint !== undefined && hint.length > 0 ? (
        <p className="text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  )
}

// Six headline cards plus supporting duration for one fluency arm (transcript or acoustic).
function FluencyArm({
  title, // "Transcript-derived" or "Acoustic (VAD)"
  testId, // fluency-transcript | fluency-acoustic
  metrics, // parsed arm; parent only renders when hasRenderableFluency
}: {
  title: string // column heading
  testId: string // stable test id
  metrics: FluencyMetricsOut // worker JSON
}) {
  return (
    <div className="flex flex-col gap-3" data-testid={testId}>
      <div className="flex flex-col gap-1">
        <p className="text-sm font-medium">{title}</p>
        <p className="text-xs text-muted-foreground">
          {metrics.word_count} words · {formatSeconds(metrics.total_duration_s)} total · {metrics.pause_count} pauses
        </p>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <MetricCard label="Speech rate" value={formatWpm(metrics.speech_rate_wpm)} />
        <MetricCard label="Articulation rate" value={formatWpm(metrics.articulation_rate_wpm)} />
        <MetricCard label="Mean pause" value={formatSeconds(metrics.mean_pause_duration_s)} />
        <MetricCard label="Pause ratio" value={formatRatioPercent(metrics.pause_ratio)} />
        <MetricCard
          label="Filler rate"
          value={formatRatioPercent(metrics.filler_rate)}
          hint={`${metrics.filler_count} filler${metrics.filler_count === 1 ? "" : "s"}`}
        />
        <MetricCard label="Filler count" value={`${metrics.filler_count}`} />
      </div>
    </div>
  )
}

// Dual-fluency panel. Both arms are shown when present; the pipeline does not pick a winner.
export function FluencyPanel({
  metrics, // parsed speech_metrics; null when the column is null
  state, // pending / failed / stored / text-only / ready
}: {
  metrics: ParsedSpeechMetrics | null // do not invent a payload in the parent
  state: SpeechAnalysisState // empty-state reason
}) {
  const transcriptArm = metrics !== null && hasRenderableFluency(metrics.fluency_transcript) ? metrics.fluency_transcript : null // ASR-gap
  const acousticArm = metrics !== null && hasRenderableFluency(metrics.fluency_acoustic) ? metrics.fluency_acoustic : null // VAD
  const prosody = metrics !== null && hasRenderableProsody(metrics.prosody) ? metrics.prosody : null // Praat
  const hasAny = transcriptArm !== null || acousticArm !== null || prosody !== null // something to render

  if (state !== "ready" || !hasAny) {
    return (
      <div className="flex flex-col gap-2" data-testid="fluency-panel">
        <p className="text-sm font-medium">Communication / fluency</p>
        <p className="text-sm text-muted-foreground" data-testid="fluency-empty">
          {emptyCopy(state)}
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4" data-testid="fluency-panel">
      <div className="flex flex-col gap-1">
        <p className="text-sm font-medium">Communication / fluency</p>
        <p className="text-xs text-muted-foreground">
          Both fluency arms are shown. The pipeline does not pick a winner — on sparse speech the transcript arm can
          report 0 pauses while the acoustic arm reports several.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {transcriptArm !== null ? (
          <FluencyArm title="Transcript-derived" testId="fluency-transcript" metrics={transcriptArm} />
        ) : (
          <p className="text-sm text-muted-foreground" data-testid="fluency-transcript-empty">
            Transcript-derived fluency is missing on this payload.
          </p>
        )}
        {acousticArm !== null ? (
          <FluencyArm title="Acoustic (VAD)" testId="fluency-acoustic" metrics={acousticArm} />
        ) : (
          <p className="text-sm text-muted-foreground" data-testid="fluency-acoustic-empty">
            Acoustic fluency is missing on this payload.
          </p>
        )}
      </div>
      {prosody !== null ? (
        <div className="flex flex-col gap-2" data-testid="prosody-summary">
          <p className="text-sm font-medium">Prosody</p>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <MetricCard label="Pitch mean" value={formatHz(prosody.pitch_mean_hz)} />
            <MetricCard label="Pitch spread" value={formatHz(prosody.pitch_std_hz)} />
            <MetricCard label="Intensity mean" value={formatDb(prosody.intensity_mean_db)} />
            <MetricCard label="Intensity spread" value={formatDb(prosody.intensity_std_db)} />
          </div>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">No prosody summary on this payload.</p>
      )}
    </div>
  )
}
