"""Weighted session scoring: config-driven weights, reconstructable attribution, PDF HTML.

`aggregate_session` is the entry the `interview_evaluate` worker calls when a session becomes
completed. It is arithmetic over already-stored ATS / judge / speech_metrics rows — never call
Ollama or Whisper from here, and never call this from a FastAPI request handler to recompute a
GET. Reading a stored `scores` row on GET is fine.

Public surface the worker, report route, and research harness should import from `ml.scoring`.
"""

from ml.scoring.aggregate import (  # session-level math
    AggregationResult,
    AnswerSignals,
    aggregate_session,
)
from ml.scoring.communication import (  # speech_metrics → 0–100 mapping
    mean_communication,
    score_fluency_arm,
    score_speech_metrics,
)
from ml.scoring.report import ReportAnswer, ReportContext, build_report_html  # HTML only; no WeasyPrint
from ml.scoring.weights import (  # Settings / .env mapping
    ALL_SIGNALS,
    FORMULA_VERSION,
    SIGNAL_BEHAVIORAL,
    SIGNAL_COMMUNICATION,
    SIGNAL_RESUME,
    SIGNAL_TECHNICAL,
    ScoringConfigError,
    ScoringWeights,
    config_from_settings,
    scale_judge_score,
)

__all__ = [  # public surface documented for the worker and research harness
    "ALL_SIGNALS",  # resume / technical / communication / behavioral
    "AggregationResult",  # composite + attribution
    "AnswerSignals",  # per-answer input to aggregate_session
    "FORMULA_VERSION",  # scoring_v1
    "ReportAnswer",  # one PDF answer block
    "ReportContext",  # PDF inputs
    "SIGNAL_BEHAVIORAL",  # attribution key
    "SIGNAL_COMMUNICATION",  # attribution key
    "SIGNAL_RESUME",  # attribution key
    "SIGNAL_TECHNICAL",  # attribution key
    "ScoringConfigError",  # invalid weights
    "ScoringWeights",  # four raw weights
    "aggregate_session",  # worker entry
    "build_report_html",  # PDF HTML
    "config_from_settings",  # Settings → ScoringWeights
    "mean_communication",  # session-level fluency mapping
    "scale_judge_score",  # 0–5 → 0–100
    "score_fluency_arm",  # one dual-fluency arm
    "score_speech_metrics",  # equal-mean of both arms
]
