"""Unit tests for `ml.scoring`. No MiniLM, Whisper, Ollama, or WeasyPrint.

Covers weight renormalization, missing-signal omission (not faked as 0), attribution summing to
the composite, judge 0–5 → 0–100 scale, and equal-mean dual-fluency mapping (not a winner arm).
"""

import pytest  # approx for float weights
from ml.scoring import (  # public surface
    FORMULA_VERSION,
    SIGNAL_BEHAVIORAL,
    SIGNAL_COMMUNICATION,
    SIGNAL_RESUME,
    SIGNAL_TECHNICAL,
    AnswerSignals,
    ScoringConfigError,
    ScoringWeights,
    aggregate_session,
    build_report_html,
    mean_communication,
    scale_judge_score,
    score_speech_metrics,
)
from ml.scoring.report import ReportAnswer, ReportContext  # HTML builder inputs


def _arm(*, wpm: float = 140.0, pause_ratio: float = 0.15, filler_rate: float = 0.02) -> dict:
    """Minimal fluency-arm JSON matching answers.speech_metrics nested objects."""
    return {
        "speech_rate_wpm": wpm,  # WPM including pauses
        "articulation_rate_wpm": 160.0,  # unused by scoring_v1 (VAD can be 0 on a sine)
        "mean_pause_duration_s": 0.4,  # unused by the mapping
        "pause_ratio": pause_ratio,  # 0–1
        "filler_rate": filler_rate,  # 0–1
        "filler_count": 1,  # unused by the mapping
        "word_count": 50,  # unused by the mapping
        "total_duration_s": 20.0,  # unused by the mapping
        "speaking_duration_s": 17.0,  # unused by the mapping
        "pause_duration_s": 3.0,  # unused by the mapping
        "pause_count": 4,  # unused by the mapping
    }


def _metrics(transcript_wpm: float = 140.0, acoustic_wpm: float = 140.0) -> dict:
    """Full-enough speech_metrics blob with both arms present."""
    return {
        "words": [],  # not used by scoring
        "language": "en",  # not used by scoring
        "duration_s": 20.0,  # not used by scoring
        "fluency_transcript": _arm(wpm=transcript_wpm),  # ASR-gap arm
        "fluency_acoustic": _arm(wpm=acoustic_wpm),  # VAD arm
        "prosody": {"pitch_mean_hz": 140.0, "pitch_std_hz": 10.0, "intensity_mean_db": 55.0, "intensity_std_db": 4.0},
        "vad": {"speech_segments": [], "pauses": []},  # not used by scoring
    }


def test_scale_judge_score_zero_five_and_mid() -> None:
    """0–5 judge maps onto the same 0–100 range as ATS (multiply by 20)."""
    assert scale_judge_score(0) == 0.0  # floor
    assert scale_judge_score(5) == 100.0  # ceiling
    assert scale_judge_score(2.5) == 50.0  # midpoint


def test_default_weights_renormalize_to_one() -> None:
    """Brief 20/30/25/15 (coding dropped) renormalize across all four signals to sum 1.0."""
    applied = ScoringWeights().applied({SIGNAL_RESUME, SIGNAL_TECHNICAL, SIGNAL_COMMUNICATION, SIGNAL_BEHAVIORAL})
    assert applied[SIGNAL_RESUME] == pytest.approx(20.0 / 90.0)  # 20/90
    assert applied[SIGNAL_TECHNICAL] == pytest.approx(30.0 / 90.0)  # 30/90
    assert applied[SIGNAL_COMMUNICATION] == pytest.approx(25.0 / 90.0)  # 25/90
    assert applied[SIGNAL_BEHAVIORAL] == pytest.approx(15.0 / 90.0)  # 15/90
    assert sum(applied.values()) == pytest.approx(1.0)  # guaranteed


def test_missing_communication_renormalizes_remaining() -> None:
    """Text-only sessions omit communication; remaining weights still sum to 1.0."""
    applied = ScoringWeights().applied({SIGNAL_RESUME, SIGNAL_TECHNICAL, SIGNAL_BEHAVIORAL})  # no speech
    assert SIGNAL_COMMUNICATION not in applied  # omitted, not weight 0 with value 0
    assert applied[SIGNAL_RESUME] == pytest.approx(20.0 / 65.0)  # 20+30+15=65
    assert applied[SIGNAL_TECHNICAL] == pytest.approx(30.0 / 65.0)  # technical
    assert applied[SIGNAL_BEHAVIORAL] == pytest.approx(15.0 / 65.0)  # behavioral
    assert sum(applied.values()) == pytest.approx(1.0)  # renormalized


def test_zero_weight_omits_signal_even_when_present() -> None:
    """A configured 0 is a research weight-sweep drop, not a fake measurement of 0."""
    weights = ScoringWeights(resume=20.0, technical=30.0, communication=0.0, behavioral=15.0)  # zero comm
    applied = weights.applied({SIGNAL_RESUME, SIGNAL_TECHNICAL, SIGNAL_COMMUNICATION, SIGNAL_BEHAVIORAL})
    assert SIGNAL_COMMUNICATION not in applied  # dropped
    assert sum(applied.values()) == pytest.approx(1.0)  # 20+30+15


def test_negative_weight_raises() -> None:
    """Negative .env values are a config error, not a silent abs()."""
    with pytest.raises(ScoringConfigError):
        ScoringWeights(resume=-1.0).applied({SIGNAL_RESUME})  # invalid


def test_no_present_signals_raises() -> None:
    """Cannot composite when every signal is missing."""
    with pytest.raises(ScoringConfigError):
        ScoringWeights().applied(set())  # empty


def test_aggregate_attribution_sums_to_composite() -> None:
    """Each signal stores weight/value/contribution; contributions sum to composite_score."""
    answers = [
        AnswerSignals(question_kind="technical", evaluation={"score": 4}, speech_metrics=None),  # 80/100
        AnswerSignals(question_kind="behavioral", evaluation={"score": 5}, speech_metrics=None),  # 100/100
    ]
    result = aggregate_session(ScoringWeights(), ats_score=70.0, answers=answers)  # text-only
    assert result.communication_score is None  # omitted, not 0
    assert SIGNAL_COMMUNICATION in result.omitted  # listed
    assert result.resume_score == pytest.approx(70.0)  # ATS
    assert result.technical_score == pytest.approx(80.0)  # 4 * 20
    assert result.behavioral_score == pytest.approx(100.0)  # 5 * 20
    signals = result.attribution["signals"]  # nested map
    contrib = sum(item["contribution"] for item in signals.values())  # reconstruct
    assert result.composite_score == pytest.approx(contrib)  # Article 86 reconstructable
    assert sum(item["weight"] for item in signals.values()) == pytest.approx(1.0)  # applied weights
    assert SIGNAL_COMMUNICATION not in signals  # not stored as value 0
    assert result.attribution["formula_version"] == FORMULA_VERSION  # scoring_v1


def test_follow_up_included_under_question_kind() -> None:
    """Follow-ups average with other answers of the same kind (they keep question_kind)."""
    answers = [
        AnswerSignals(question_kind="technical", evaluation={"score": 2}, speech_metrics=None),  # original
        AnswerSignals(question_kind="technical", evaluation={"score": 4}, speech_metrics=None),  # follow-up
    ]
    result = aggregate_session(ScoringWeights(), ats_score=50.0, answers=answers)
    assert result.technical_score == pytest.approx(60.0)  # mean 3 * 20
    assert result.behavioral_score is None  # no behavioral rows


def test_missing_evaluation_does_not_count_as_zero() -> None:
    """A failed evaluate (evaluation null) omits that row; it does not drag the mean to 0."""
    answers = [
        AnswerSignals(question_kind="technical", evaluation=None, speech_metrics=None),  # failed judge
        AnswerSignals(question_kind="technical", evaluation={"score": 5}, speech_metrics=None),  # succeeded
    ]
    result = aggregate_session(ScoringWeights(), ats_score=None, answers=answers)  # no ATS
    assert result.resume_score is None  # omitted
    assert result.technical_score == pytest.approx(100.0)  # only the scored row


def test_communication_equal_mean_does_not_pick_a_winner() -> None:
    """Both fluency arms are averaged; max() would pick the faster arm and is forbidden."""
    metrics = _metrics(transcript_wpm=140.0, acoustic_wpm=20.0)  # arms disagree (Phase 12 sine-style split)
    equal = score_speech_metrics(metrics)  # equal mean of two arm scores
    transcript_only = score_speech_metrics({"fluency_transcript": _arm(wpm=140.0)})  # one arm
    acoustic_only = score_speech_metrics({"fluency_acoustic": _arm(wpm=20.0)})  # one arm
    assert equal is not None and transcript_only is not None and acoustic_only is not None  # all measured
    assert equal == pytest.approx((transcript_only + acoustic_only) / 2.0)  # not max, not min
    assert equal != pytest.approx(max(transcript_only, acoustic_only))  # winner would be the 140 WPM arm


def test_text_only_mean_communication_is_none() -> None:
    """Null speech_metrics must not become a fake fluency 0."""
    assert mean_communication([None, None]) is None  # omit the signal
    assert score_speech_metrics(None) is None  # one answer


def test_measured_zero_pause_is_not_missing() -> None:
    """pause_ratio 0 on a successful payload is a real measurement and scores the pause component at 100."""
    metrics = {
        "fluency_transcript": _arm(wpm=140.0, pause_ratio=0.0, filler_rate=0.0),  # fluent, no pauses
        "fluency_acoustic": _arm(wpm=140.0, pause_ratio=0.0, filler_rate=0.0),  # same
    }
    scored = score_speech_metrics(metrics)
    assert scored is not None  # present
    assert scored > 90.0  # plateau WPM + full pause + full filler


def test_build_report_html_shows_both_fluency_arms() -> None:
    """PDF HTML must not hide dual fluency or invent metrics for a text-only answer."""
    spoken = ReportAnswer(
        question_order=0,  # first
        question_kind="technical",  # kind
        is_follow_up=False,  # original
        question_text="What is a list?",  # prompt
        answer_text="A mutable sequence.",  # text
        evaluation={"score": 4, "rationale": "Clear.", "strengths": ["definition"], "improvements": []},  # judge
        transcript="A mutable sequence.",  # Whisper
        speech_metrics=_metrics(),  # both arms
    )
    silent = ReportAnswer(
        question_order=1,  # second
        question_kind="behavioral",  # kind
        is_follow_up=False,  # original
        question_text="Tell me about a conflict.",  # prompt
        answer_text="We talked it through.",  # text
        evaluation={"score": 4, "rationale": "Ok.", "strengths": [], "improvements": []},  # judge
        transcript=None,  # text-only
        speech_metrics=None,  # do not invent
    )
    html = build_report_html(
        ReportContext(
            session_id="00000000-0000-0000-0000-000000000001",  # stable
            status="completed",  # reports are for completed sessions
            candidate_email="c@example.com",  # cover
            posting_title=None,  # practice
            ats_score=70.0,  # ATS
            ats_breakdown={"section_points": 20},  # checklist
            resume_score=70.0,  # stored
            technical_score=80.0,  # stored
            communication_score=None,  # omitted example on the cover still uses —
            behavioral_score=80.0,  # stored
            composite_score=76.0,  # stored
            attribution={
                "formula_version": FORMULA_VERSION,  # scoring_v1
                "judge_scale": "evaluation.score 0-5 * 20 -> 0-100",  # documented
                "communication_arm_policy": "equal_mean of fluency_transcript and fluency_acoustic",  # not a winner
                "omitted": ["communication"],  # listed
                "signals": {
                    SIGNAL_RESUME: {"weight": 0.4, "value": 70.0, "contribution": 28.0},  # example
                    SIGNAL_TECHNICAL: {"weight": 0.6, "value": 80.0, "contribution": 48.0},  # example
                },
            },
            answers=[spoken, silent],  # mixed
            generated_at="2026-09-13T00:00:00+00:00",  # stamp
        )
    )
    assert "Fluency (transcript arm)" in html  # both arms
    assert "Fluency (acoustic arm)" in html  # both arms
    assert "not invented" in html  # text-only copy
    assert "Practice (no posting)" in html  # job_id null
    assert "What is a list?" in html  # escaped prompt still visible
    assert "<script>" not in html  # no extra JS
