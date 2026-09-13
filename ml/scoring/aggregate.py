"""Weighted aggregation of four session signals into a reconstructable Score row.

Signals (all on 0–100 before weighting):

- resume: that session's `resumes.ats_score` (already 0–100). Omitted if null.
- technical / behavioral: mean of `answers.evaluation.score` (0–5) for rows of that
  `question_kind`, including follow-ups, then `scale_judge_score` (* 20). Omitted if no
  evaluated answers of that kind.
- communication: `mean_communication` over existing `speech_metrics`. Text-only sessions omit
  this signal (they do not invent fluency numbers and do not store 0 as a fake measurement).

Missing signals drop out; remaining configured weights renormalize to 1.0. Attribution stores
each kept signal as `{weight, value, contribution}` plus metadata so a later weight swap can
still explain this composite (EU AI Act Article 86 + research weight-sensitivity).
"""

from __future__ import annotations  # AnswerSignals / AggregationResult forward refs

from dataclasses import dataclass  # plain value objects; no ORM in ml/
from typing import Any  # evaluation / speech_metrics JSON blobs

from ml.scoring.communication import mean_communication  # speech_metrics → 0–100 or None
from ml.scoring.weights import (  # config + scale + signal names
    ALL_SIGNALS,
    FORMULA_VERSION,
    SIGNAL_BEHAVIORAL,
    SIGNAL_COMMUNICATION,
    SIGNAL_RESUME,
    SIGNAL_SCALE,
    SIGNAL_TECHNICAL,
    ScoringWeights,
    scale_judge_score,
)

# question_kind values written by interview_generate / follow-up (varchar, not a Postgres ENUM).
KIND_TECHNICAL = "technical"  # uses technical_answer_v1 rubric
KIND_BEHAVIORAL = "behavioral"  # uses behavioral_answer_v1 rubric


@dataclass(frozen=True)
class AnswerSignals:
    """One answers row reduced to the fields aggregation needs. No ORM, no audio bytes."""

    question_kind: str  # "technical" | "behavioral" (follow-ups keep their kind)
    evaluation: dict[str, Any] | None  # {score, rationale, strengths, improvements} or None
    speech_metrics: dict[str, Any] | None  # dual fluency JSON or None (text-only)


@dataclass(frozen=True)
class AggregationResult:
    """Per-signal scores plus the composite and the JSON blob written to scores.attribution."""

    resume_score: float | None  # ATS 0–100 or None when omitted
    technical_score: float | None  # scaled judge mean or None
    communication_score: float | None  # mapped fluency or None
    behavioral_score: float | None  # scaled judge mean or None
    composite_score: float | None  # sum of contributions; None if nothing could be weighted
    omitted: tuple[str, ...]  # signal names dropped (missing data or non-positive weight)
    attribution: dict[str, Any]  # reconstructable explanation persisted on scores.attribution

    def column_values(self) -> dict[str, Any]:
        """Keyword args for the Score ORM columns (excluding session_id)."""
        return {
            "resume_score": self.resume_score,  # nullable Float
            "technical_score": self.technical_score,  # nullable Float
            "communication_score": self.communication_score,  # nullable Float
            "behavioral_score": self.behavioral_score,  # nullable Float
            "composite_score": self.composite_score,  # nullable Float; set only when completed
            "attribution": self.attribution,  # JSON
        }


def _mean_kind_score(answers: list[AnswerSignals], kind: str) -> float | None:
    """Mean of evaluation.score for this question_kind, scaled 0–5 → 0–100. None if none scored."""
    values: list[float] = []  # raw 0–5 judge scores
    for item in answers:
        if item.question_kind != kind:
            continue  # other kind (or unexpected string) does not mix in
        if not isinstance(item.evaluation, dict):
            continue  # evaluate failed or has not run; do not treat as 0
        raw = item.evaluation.get("score")  # AnswerEvaluation.score
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            continue  # bool is a subclass of int; skip garbage
        values.append(float(raw))  # include a legitimate 0
    if not values:
        return None  # omit this interview-kind signal
    mean_raw = sum(values) / float(len(values))  # still 0–5
    return scale_judge_score(mean_raw)  # * 20 → 0–100


def aggregate_session(
    weights: ScoringWeights,
    *,
    ats_score: float | None,
    answers: list[AnswerSignals],
) -> AggregationResult:
    """Build the four signals, drop missing ones, renormalize weights, persist attribution.

    Does not call Ollama or Whisper. `ats_score` is the session resume's stored ATS; `answers`
    are already-loaded evaluation / speech_metrics dicts. Raises ScoringConfigError if remaining
    weights cannot renormalize (all zero / all missing).
    """
    resume_value: float | None
    if ats_score is None:
        resume_value = None  # parsed resume should have ATS; omit rather than invent 0
    else:
        resume_value = float(ats_score)  # already 0–100 from ml.resume.ats
        if resume_value < 0.0 or resume_value > SIGNAL_SCALE:
            resume_value = max(0.0, min(SIGNAL_SCALE, resume_value))  # belt-and-suspenders; ATS is 0–100
    technical_value = _mean_kind_score(answers, KIND_TECHNICAL)  # None if no technical evaluations
    behavioral_value = _mean_kind_score(answers, KIND_BEHAVIORAL)  # None if no behavioral evaluations
    communication_value = mean_communication([item.speech_metrics for item in answers])  # None if all text-only

    measured: dict[str, float | None] = {
        SIGNAL_RESUME: resume_value,  # ATS
        SIGNAL_TECHNICAL: technical_value,  # scaled judge
        SIGNAL_COMMUNICATION: communication_value,  # mapped dual fluency
        SIGNAL_BEHAVIORAL: behavioral_value,  # scaled judge
    }
    present = {name for name, value in measured.items() if value is not None}  # omit missing measurements
    applied = weights.applied(present)  # renormalize; raises if nothing left
    omitted = tuple(name for name in ALL_SIGNALS if name not in applied)  # missing data or zero weight

    signals_json: dict[str, dict[str, float]] = {}  # Score-model shape: weight / value / contribution
    composite = 0.0  # running weighted sum
    for name, weight in applied.items():
        value = float(measured[name])  # present ⇒ not None
        contribution = weight * value  # reconstructable: composite = sum(contribution)
        signals_json[name] = {
            "weight": weight,  # applied (renormalized) weight, not the raw .env number
            "value": value,  # 0–100
            "contribution": contribution,  # weight * value
        }
        composite += contribution  # arithmetic only; no learned scorer

    attribution = {
        "formula_version": FORMULA_VERSION,  # scoring_v1
        "judge_scale": "evaluation.score 0-5 * 20 -> 0-100",  # documented scale
        "communication_arm_policy": "equal_mean of fluency_transcript and fluency_acoustic",  # not a winner
        "configured_weights": weights.as_dict(),  # raw .env numbers so a later swap can still explain this row
        "omitted": list(omitted),  # signals dropped for this session
        "signals": signals_json,  # the Score model comment's {weight, value, contribution} map
    }
    return AggregationResult(
        resume_score=resume_value,  # stored even when omitted from weighting (null)
        technical_score=technical_value,  # stored even when omitted
        communication_score=communication_value,  # null on text-only; never a fake 0
        behavioral_score=behavioral_value,  # stored even when omitted
        composite_score=composite,  # sum of contributions
        omitted=omitted,  # tuple for tests
        attribution=attribution,  # JSON blob
    )


# Re-export so callers catching config errors need one import path.
__all__ = [  # public names from this module (package __init__ re-exports a wider surface)
    "AnswerSignals",  # per-answer input
    "AggregationResult",  # output written onto scores
    "KIND_BEHAVIORAL",  # question_kind filter
    "KIND_TECHNICAL",  # question_kind filter
    "aggregate_session",  # the worker entry
]
