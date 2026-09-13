"""Map existing `answers.speech_metrics` onto a 0–100 communication_score.

This is a documented piecewise function (`scoring_v1`), not a trained model and not a silent
overwrite of speech_metrics. Both fluency arms are scored with the same function and then
averaged — the pipeline does not pick a winner inside `ml.speech` or here.

Text-only answers (speech_metrics is null) contribute nothing. Zeros on a *successful* payload
are real worker values (e.g. pause_count 0) and are scored as measurements, not treated as missing.

v1 uses three components that exist on both arms: speech_rate_wpm, pause_ratio, filler_rate.
Articulation rate is intentionally excluded: the acoustic arm can report 0 WPM articulation when
Silero does not treat a tone as voiced (Phase 12 sine-WebM gotcha). Folding that in would silently
punish the acoustic arm. Pitch/intensity stay in the PDF as facts, not as a quality score.
"""

from __future__ import annotations  # dict | None on helpers without quotes

from typing import Any  # speech_metrics JSON is a nested dict from answers.speech_metrics

# Conversational / interview speech-rate plateau (WPM). Tauroza & Allison 1990 place "average"
# spoken English around 125–160 WPM; interview answers cluster similarly. Below 110 is slow;
# above 160 starts to sound rushed; 240 is treated as unintelligible-fast → 0.
SPEECH_RATE_ZERO_LO = 0.0  # 0 WPM → component 0
SPEECH_RATE_PEAK_LO = 110.0  # start of the 100-point plateau
SPEECH_RATE_PEAK_HI = 160.0  # end of the 100-point plateau
SPEECH_RATE_ZERO_HI = 240.0  # 240 WPM and above → component 0

# Interview answers include thinking pauses. Up to 40% pause time still scores 100; 85% → 0.
PAUSE_RATIO_FULL = 0.40  # pause_ratio <= 0.40 is full marks (thinking is allowed)
PAUSE_RATIO_ZERO = 0.85  # pause_ratio >= 0.85 is component 0

# Filler tokens as a fraction of words. Up to 5% is typical; 20% is heavily disfluent → 0.
FILLER_RATE_FULL = 0.05  # filler_rate <= 0.05 is full marks
FILLER_RATE_ZERO = 0.20  # filler_rate >= 0.20 is component 0

# Both arms always contribute equally when both are present. Do not take max() or min().
ARM_KEYS = ("fluency_transcript", "fluency_acoustic")  # JSON keys on answers.speech_metrics


def _triangular_plateau(value: float, zero_lo: float, peak_lo: float, peak_hi: float, zero_hi: float) -> float:
    """0 outside [zero_lo, zero_hi], 100 on [peak_lo, peak_hi], linear ramps in between."""
    x = float(value)  # JSON numbers may arrive as int
    if x <= zero_lo or x >= zero_hi:
        return 0.0  # outside the support of the triangle
    if peak_lo <= x <= peak_hi:
        return 100.0  # plateau
    if x < peak_lo:
        span = peak_lo - zero_lo  # rising ramp width
        return 100.0 * (x - zero_lo) / span if span > 0.0 else 0.0  # linear 0 → 100
    span = zero_hi - peak_hi  # falling ramp width
    return 100.0 * (zero_hi - x) / span if span > 0.0 else 0.0  # linear 100 → 0


def _inverted_linear(value: float, full_until: float, zero_at: float) -> float:
    """100 while value <= full_until, then linear down to 0 at zero_at (and 0 beyond)."""
    x = float(value)  # JSON numbers may arrive as int
    if x <= full_until:
        return 100.0  # still in the "fine" band
    if x >= zero_at:
        return 0.0  # at or past the floor
    span = zero_at - full_until  # falling ramp width
    return 100.0 * (zero_at - x) / span if span > 0.0 else 0.0  # linear 100 → 0


def score_fluency_arm(arm: dict[str, Any]) -> float | None:
    """Score one fluency arm (transcript or acoustic) on 0–100. None if required keys are missing."""
    if "speech_rate_wpm" not in arm or "pause_ratio" not in arm or "filler_rate" not in arm:
        return None  # incomplete JSON is missing, not a measured zero
    rate = _triangular_plateau(
        float(arm["speech_rate_wpm"]),  # WPM including pauses
        SPEECH_RATE_ZERO_LO,  # 0 WPM
        SPEECH_RATE_PEAK_LO,  # 110
        SPEECH_RATE_PEAK_HI,  # 160
        SPEECH_RATE_ZERO_HI,  # 240
    )
    pause = _inverted_linear(float(arm["pause_ratio"]), PAUSE_RATIO_FULL, PAUSE_RATIO_ZERO)  # 0–1 fraction
    filler = _inverted_linear(float(arm["filler_rate"]), FILLER_RATE_FULL, FILLER_RATE_ZERO)  # 0–1 fraction
    return (rate + pause + filler) / 3.0  # equal components; not a learned mix


def score_speech_metrics(speech_metrics: dict[str, Any] | None) -> float | None:
    """Equal-mean of both fluency arms. None when speech_metrics is missing or neither arm is scorable.

    Dual fluency is mandatory in storage; this function still averages rather than picking the
    "better" arm. A sparse ASR arm (20 WPM, 0 pauses) averaged with an acoustic arm that shows
    several pauses is the documented mapping — it is not a bug.
    """
    if not isinstance(speech_metrics, dict):
        return None  # text-only / transcribe-failed / never-uploaded
    arm_scores: list[float] = []  # one entry per scorable arm
    for key in ARM_KEYS:
        raw = speech_metrics.get(key)  # fluency_transcript / fluency_acoustic
        if not isinstance(raw, dict):
            continue  # missing arm JSON is omitted, not scored as 0
        scored = score_fluency_arm(raw)  # 0–100 or None
        if scored is not None:
            arm_scores.append(scored)  # measured, including a legitimate 0.0
    if not arm_scores:
        return None  # nothing to average
    return sum(arm_scores) / float(len(arm_scores))  # 1 arm → that arm; 2 arms → equal mean


def mean_communication(metrics_list: list[dict[str, Any] | None]) -> float | None:
    """Session communication_score: mean of per-answer mappings. Null metrics do not count as 0."""
    scores: list[float] = []  # only answers that actually have speech_metrics
    for item in metrics_list:
        scored = score_speech_metrics(item)  # None when text-only
        if scored is not None:
            scores.append(scored)  # include measured zeros
    if not scores:
        return None  # omit the communication signal and renormalize the other weights
    return sum(scores) / float(len(scores))  # unweighted mean across answers that had audio
