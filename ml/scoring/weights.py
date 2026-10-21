"""Config-driven scoring weights. Never hardcode these at call sites.

The original brief used 20/30/25/15/10 including coding. Coding was dropped (plan Part 0 / Part 4),
so the four remaining weights normalize to sum to 1.0. All four signals are required (scoring_v2).
Defaults keep the brief's 20/30/25/15 proportions (divide by 90).
Product code must use `config_from_settings(get_settings())` because
pydantic-settings does not copy `.env` into `os.environ`.
"""

from __future__ import annotations  # ScoringWeights helpers can mention the class without quotes

import os  # ScoringWeights.from_env reads the same names as .env.example / Settings
from dataclasses import dataclass  # ScoringWeights is a plain value object, independent of FastAPI Settings
from typing import Any  # config_from_settings is duck-typed so ml/ does not import app.core.config

# Signal keys stored on scores.attribution["signals"] and as Score column names without _score.
SIGNAL_RESUME = "resume"  # resumes.ats_score mapped 0–100
SIGNAL_TECHNICAL = "technical"  # mean of technical answers' evaluation.score, scaled 0–5 → 0–100
SIGNAL_COMMUNICATION = "communication"  # mapped from speech_metrics; required in scoring_v2
SIGNAL_BEHAVIORAL = "behavioral"  # mean of behavioral answers' evaluation.score, scaled 0–5 → 0–100
ALL_SIGNALS = (SIGNAL_RESUME, SIGNAL_TECHNICAL, SIGNAL_COMMUNICATION, SIGNAL_BEHAVIORAL)  # iteration order for reports

# Brief percentages before coding was dropped. Coding was 10%; the remainder is 90.
DEFAULT_WEIGHT_RESUME = 20.0  # SCORE_WEIGHT_RESUME; 20/90 after coding is dropped
DEFAULT_WEIGHT_TECHNICAL = 30.0  # SCORE_WEIGHT_TECHNICAL; 30/90
DEFAULT_WEIGHT_COMMUNICATION = 25.0  # SCORE_WEIGHT_COMMUNICATION; 25/90
DEFAULT_WEIGHT_BEHAVIORAL = 15.0  # SCORE_WEIGHT_BEHAVIORAL; 15/90

# Version string persisted in attribution so a later formula swap can still explain an old composite.
FORMULA_VERSION = "scoring_v2"  # v2: all four signals required, no omission or renormalizing by dropping

# Judge JSON is 0–5 inclusive; ATS is already 0–100. Scale the judge onto the same range before weighting.
JUDGE_SCORE_MAX = 5.0  # AnswerEvaluation.score upper bound from ml.llm
SIGNAL_SCALE = 100.0  # every weighted signal is on 0–100 before weight * value


class ScoringConfigError(ValueError):
    """Invalid configured weights (negative, or nothing left to renormalize)."""


@dataclass(frozen=True)
class ScoringWeights:
    """Four raw weights from Settings / .env. Call `applied()` to normalize them over all four signals.

    Raw values may be percentages (20/30/25/15) or already-unit fractions. `applied()` only cares
    about their ratios. A zero weight keeps the signal listed with contribution 0.
    """

    resume: float = DEFAULT_WEIGHT_RESUME  # SCORE_WEIGHT_RESUME
    technical: float = DEFAULT_WEIGHT_TECHNICAL  # SCORE_WEIGHT_TECHNICAL
    communication: float = DEFAULT_WEIGHT_COMMUNICATION  # SCORE_WEIGHT_COMMUNICATION
    behavioral: float = DEFAULT_WEIGHT_BEHAVIORAL  # SCORE_WEIGHT_BEHAVIORAL

    @classmethod
    def from_env(cls) -> ScoringWeights:
        """Build from process env using the same names as `.env.example`.

        Product code must prefer `config_from_settings(get_settings())`. This helper is for a
        research harness that exported the vars (or called `load_dotenv`) itself.
        """
        return cls(
            resume=float(os.environ.get("SCORE_WEIGHT_RESUME", str(DEFAULT_WEIGHT_RESUME))),  # resume
            technical=float(os.environ.get("SCORE_WEIGHT_TECHNICAL", str(DEFAULT_WEIGHT_TECHNICAL))),  # technical
            communication=float(
                os.environ.get("SCORE_WEIGHT_COMMUNICATION", str(DEFAULT_WEIGHT_COMMUNICATION))
            ),  # speech
            behavioral=float(os.environ.get("SCORE_WEIGHT_BEHAVIORAL", str(DEFAULT_WEIGHT_BEHAVIORAL))),  # behavioral
        )

    def as_dict(self) -> dict[str, float]:
        """Raw configured weights keyed by signal name, in ALL_SIGNALS order."""
        return {
            SIGNAL_RESUME: float(self.resume),  # may be 20.0 or 0.222… depending on how .env was filled
            SIGNAL_TECHNICAL: float(self.technical),  # same
            SIGNAL_COMMUNICATION: float(self.communication),  # same
            SIGNAL_BEHAVIORAL: float(self.behavioral),  # same
        }

    def applied(self) -> dict[str, float]:
        """Normalize the four configured weights so they sum to 1.0 (20/90, 30/90, 25/90, 15/90 by default).

        Every signal is required in scoring_v2, so there is no "present" set and nothing is dropped
        for missing data. A zero weight stays listed with weight 0.0 (a research weight sweep can
        silence an arm without changing which signals exist). Raises ScoringConfigError on a
        negative weight or when all four are zero.
        """
        raw = self.as_dict()  # four configured numbers, ALL_SIGNALS order
        for name, value in raw.items():
            if value < 0.0:
                raise ScoringConfigError(f"scoring weight for {name} must be >= 0, got {value}")  # misconfigured .env
        total = sum(raw.values())  # 90.0 with the defaults
        if total <= 0.0:
            raise ScoringConfigError("at least one scoring weight must be positive")  # all zero cannot normalize
        return {name: value / total for name, value in raw.items()}  # sums to 1.0; zero weights stay as 0.0


def config_from_settings(settings: Any) -> ScoringWeights:
    """Map a Settings-like object onto `ScoringWeights` without importing FastAPI."""
    return ScoringWeights(
        resume=float(getattr(settings, "score_weight_resume", DEFAULT_WEIGHT_RESUME)),  # Settings.score_weight_resume
        technical=float(getattr(settings, "score_weight_technical", DEFAULT_WEIGHT_TECHNICAL)),  # technical
        communication=float(getattr(settings, "score_weight_communication", DEFAULT_WEIGHT_COMMUNICATION)),  # speech
        behavioral=float(getattr(settings, "score_weight_behavioral", DEFAULT_WEIGHT_BEHAVIORAL)),  # behavioral
    )


def scale_judge_score(score: float) -> float:
    """Map an AnswerEvaluation 0–5 score onto the 0–100 ATS range (multiply by 20).

    Out-of-range values are not clamped here: the judge schema already rejected them at evaluate
    time. A missing/non-numeric score is the caller's problem (they should omit the signal).
    """
    return float(score) * (SIGNAL_SCALE / JUDGE_SCORE_MAX)  # 0→0, 2.5→50, 5→100
