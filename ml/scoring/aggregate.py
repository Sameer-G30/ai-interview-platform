"""Weighted aggregation of four required session signals into a reconstructable Score row (`scoring_v2`).

Signals (all on 0-100 before weighting):

- resume: that session's `resumes.ats_score` (already 0-100).
- technical / behavioral: mean of `answers.evaluation.score` (0-5) for rows of that
  `question_kind`, including follow-ups, then `scale_judge_score` (* 20).
- communication: `mean_communication` over `speech_metrics` (both fluency arms, equal mean).

All four are required. A missing signal raises `IncompleteSignalsError`; nothing is omitted,
stored as null, or faked as 0, and weights are never renormalized by dropping a signal. Attribution
stores each signal as `{weight, value, contribution}` plus metadata so a later weight swap can still
explain this composite (EU AI Act Article 86 + research weight-sensitivity).
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


class IncompleteSignalsError(ValueError):
    """A session cannot be scored because one or more of the four signals is unmeasured."""

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing  # signal names in ALL_SIGNALS order
        super().__init__(f"missing signals: {', '.join(missing)}")  # short text the failed job surfaces


@dataclass(frozen=True)
class AnswerSignals:
    """One answers row reduced to the fields aggregation needs. No ORM, no audio bytes."""

    question_kind: str  # "technical" | "behavioral" (follow-ups keep their kind)
    evaluation: dict[str, Any] | None  # {score, rationale, strengths, improvements} or None
    speech_metrics: dict[str, Any] | None  # dual fluency JSON or None (text-only)


@dataclass(frozen=True)
class AggregationResult:
    """Per-signal scores plus the composite and the JSON blob written to scores.attribution."""

    resume_score: float  # ATS 0-100
    technical_score: float  # scaled judge mean
    communication_score: float  # mapped fluency
    behavioral_score: float  # scaled judge mean
    composite_score: float  # sum of contributions
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
    """Build all four signals, apply the normalized weights, and persist attribution (`scoring_v2`).

    Does not call Ollama or Whisper. `ats_score` is the session resume's stored ATS; `answers` are
    already-loaded evaluation / speech_metrics dicts. Raises IncompleteSignalsError naming every
    signal that could not be measured: no omission, no JSON null, no invented 0.
    """
    resume_value: float | None = None  # stays None only when the resume has no ATS score
    if ats_score is not None:
        resume_value = max(0.0, min(SIGNAL_SCALE, float(ats_score)))  # ATS is already 0-100; clamp is a safety net
    technical_value = _mean_kind_score(answers, KIND_TECHNICAL)  # None if no technical evaluation
    behavioral_value = _mean_kind_score(answers, KIND_BEHAVIORAL)  # None if no behavioral evaluation
    communication_value = mean_communication([item.speech_metrics for item in answers])  # None if no scorable speech

    measured: dict[str, float | None] = {
        SIGNAL_RESUME: resume_value,  # ATS
        SIGNAL_TECHNICAL: technical_value,  # scaled judge
        SIGNAL_COMMUNICATION: communication_value,  # mapped dual fluency
        SIGNAL_BEHAVIORAL: behavioral_value,  # scaled judge
    }
    missing = tuple(name for name in ALL_SIGNALS if measured[name] is None)  # stable ALL_SIGNALS order
    if missing:
        raise IncompleteSignalsError(missing)  # the caller keeps the session open and reports which are missing

    applied = weights.applied()  # all four, normalized; may raise ScoringConfigError
    signals_json: dict[str, dict[str, float]] = {}  # Score-model shape: weight / value / contribution
    composite = 0.0  # running weighted sum
    for name in ALL_SIGNALS:
        value = float(measured[name])  # all present by the check above
        contribution = applied[name] * value  # reconstructable: composite = sum(contribution)
        signals_json[name] = {
            "weight": applied[name],  # normalized weight (0.0 stays listed)
            "value": value,  # 0-100
            "contribution": contribution,  # weight * value
        }
        composite += contribution  # arithmetic only; no learned scorer

    raw_weights = weights.as_dict()  # configured numbers, e.g. 20/30/25/15
    attribution = {
        "formula_version": FORMULA_VERSION,  # scoring_v2
        "judge_scale": "evaluation.score 0-5 * 20 -> 0-100",  # documented scale
        "communication_arm_policy": "equal_mean of fluency_transcript and fluency_acoustic",  # not a winner
        "configured_weights": raw_weights,  # raw .env numbers so a later swap can still explain this row
        "weight_denominator": sum(raw_weights.values()),  # 90 with the defaults
        "signals": signals_json,  # all four entries
    }
    return AggregationResult(
        resume_score=resume_value,  # always a number in v2
        technical_score=technical_value,  # always a number in v2
        communication_score=communication_value,  # always a number in v2
        behavioral_score=behavioral_value,  # always a number in v2
        composite_score=composite,  # sum of contributions
        attribution=attribution,  # JSON blob
    )


# Re-export so callers catching config errors need one import path.
__all__ = [  # public names from this module (package __init__ re-exports a wider surface)
    "AnswerSignals",  # per-answer input
    "AggregationResult",  # output written onto scores
    "IncompleteSignalsError",  # a signal could not be measured
    "KIND_BEHAVIORAL",  # question_kind filter
    "KIND_TECHNICAL",  # question_kind filter
    "aggregate_session",  # the worker entry
]
