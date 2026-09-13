"""Pure HTML builder for a reconstructable interview PDF. Does not import WeasyPrint.

The FastAPI report route loads already-stored Score / session / answer / resume rows and passes
them here. Rendering to PDF bytes (cairo/pango) lives in `app.services.pdf_report` so unit tests
of this module never need system libraries. Dual fluency is printed as facts for both arms.
"""

from __future__ import annotations  # ReportAnswer / ReportContext without quotes

import html  # escape candidate/recruiter-facing text so a question cannot break the document
from dataclasses import dataclass  # report input is a plain value object, not ORM
from typing import Any  # evaluation / speech_metrics / attribution JSON


@dataclass(frozen=True)
class ReportAnswer:
    """One answers row as the PDF should render it (already loaded; no Whisper/Ollama)."""

    question_order: int  # 0-based ask order
    question_kind: str  # technical | behavioral
    is_follow_up: bool  # True when evaluate appended this row
    question_text: str  # generated prompt
    answer_text: str | None  # submitted text; None should not happen on a completed session
    evaluation: dict[str, Any] | None  # judge JSON
    transcript: str | None  # Whisper string; None for text-only
    speech_metrics: dict[str, Any] | None  # dual fluency; None for text-only


@dataclass(frozen=True)
class ReportContext:
    """Everything the HTML template needs. Composite comes from the stored Score, not a recompute."""

    session_id: str  # UUID string
    status: str  # completed (reports are refused for abandoned)
    candidate_email: str  # owner of the session
    posting_title: str | None  # None for a practice interview
    ats_score: float | None  # resumes.ats_score
    ats_breakdown: dict[str, Any] | None  # parsed_data.ats_breakdown when present
    resume_score: float | None  # scores.resume_score
    technical_score: float | None  # scores.technical_score
    communication_score: float | None  # scores.communication_score
    behavioral_score: float | None  # scores.behavioral_score
    composite_score: float | None  # scores.composite_score
    attribution: dict[str, Any]  # scores.attribution
    answers: list[ReportAnswer]  # in question_order
    generated_at: str  # ISO timestamp of PDF generation (not of the score write)


def _esc(value: object) -> str:
    """HTML-escape a value for text nodes. None becomes an em dash."""
    if value is None:
        return "—"  # missing field, not a fake 0
    return html.escape(str(value), quote=True)  # quote=True also covers attribute use


def _fmt_score(value: float | None) -> str:
    """One decimal place for 0–100 scores; em dash when the signal was omitted."""
    if value is None:
        return "—"  # omitted signal
    return f"{float(value):.1f}"  # 78.0 → "78.0"


def _fmt_list(items: object) -> str:
    """Join a JSON list of strings (strengths / improvements) as a comma-separated sentence."""
    if not isinstance(items, list) or not items:
        return "—"  # empty judge list
    parts = [_esc(item) for item in items if str(item).strip()]  # skip blanks
    return ", ".join(parts) if parts else "—"  # still a dash if everything was whitespace


def _fluency_dl(arm: dict[str, Any] | None, title: str) -> str:
    """Render one fluency arm as a definition list. Missing arm stays visible as 'not recorded'."""
    if not isinstance(arm, dict):
        return f"<h4>{_esc(title)}</h4><p>Not recorded on this answer.</p>"  # do not invent zeros
    rows = [
        ("Speech rate (WPM)", arm.get("speech_rate_wpm")),  # including pauses
        ("Articulation rate (WPM)", arm.get("articulation_rate_wpm")),  # excluding pauses
        ("Mean pause (s)", arm.get("mean_pause_duration_s")),  # seconds
        ("Pause ratio", arm.get("pause_ratio")),  # 0–1
        ("Filler rate", arm.get("filler_rate")),  # 0–1
        ("Filler count", arm.get("filler_count")),  # integer
        ("Pause count", arm.get("pause_count")),  # integer
    ]
    items = "".join(
        f"<div><dt>{_esc(label)}</dt><dd>{_esc(value if value is not None else '—')}</dd></div>"
        for label, value in rows
    )
    return f"<h4>{_esc(title)}</h4><dl class='metrics'>{items}</dl>"  # both arms always get a heading


def _signals_table(attribution: dict[str, Any]) -> str:
    """Rebuild the weight / value / contribution table from stored attribution (not live Settings)."""
    signals = attribution.get("signals") if isinstance(attribution, dict) else None  # nested map
    if not isinstance(signals, dict) or not signals:
        return "<p>No per-signal attribution was stored for this session.</p>"  # should not happen
    header = "<tr><th>Signal</th><th>Weight</th><th>Value (0–100)</th><th>Contribution</th></tr>"  # column heads
    body_rows: list[str] = []  # one <tr> per signal
    for name, payload in signals.items():
        if not isinstance(payload, dict):
            continue  # skip garbage keys
        body_rows.append(
            "<tr>"
            f"<td>{_esc(name)}</td>"
            f"<td>{_esc(payload.get('weight'))}</td>"
            f"<td>{_esc(payload.get('value'))}</td>"
            f"<td>{_esc(payload.get('contribution'))}</td>"
            "</tr>"
        )
    omitted = attribution.get("omitted") if isinstance(attribution, dict) else None  # list of names
    omitted_note = ""  # default: nothing omitted
    if isinstance(omitted, list) and omitted:
        names = ", ".join(_esc(item) for item in omitted)  # e.g. communication on text-only
        omitted_note = f"<p class='note'>Omitted this session (not faked as 0): {names}.</p>"
    version = _esc(attribution.get("formula_version"))  # scoring_v1
    policy = _esc(attribution.get("communication_arm_policy"))  # equal-mean
    judge = _esc(attribution.get("judge_scale"))  # 0-5 * 20
    meta = (
        f"<p class='note'>Formula {version}. Judge scale: {judge}. "
        f"Communication arms: {policy}. Weights in the table are the ones applied to this composite "
        f"(renormalized); raw configured weights stay under attribution.configured_weights.</p>"
    )
    return f"<table>{header}{''.join(body_rows)}</table>{omitted_note}{meta}"  # reconstructable block


def _answer_section(answer: ReportAnswer) -> str:
    """One question's evaluation + optional dual fluency. Grammar/vocab stay inside the judge JSON."""
    follow = " (follow-up)" if answer.is_follow_up else ""  # evaluate-appended probe
    heading = f"<h3>Q{answer.question_order + 1} — {_esc(answer.question_kind)}{follow}</h3>"  # 1-based label
    question = f"<p><strong>Question.</strong> {_esc(answer.question_text)}</p>"  # prompt
    spoken = f"<p><strong>Answer (text).</strong> {_esc(answer.answer_text)}</p>"  # submitted text
    evaluation = answer.evaluation if isinstance(answer.evaluation, dict) else {}  # may be empty
    judge = (
        "<p><strong>Judge (0–5).</strong> "
        f"score={_esc(evaluation.get('score'))}. "
        f"{_esc(evaluation.get('rationale'))}</p>"
        f"<p><strong>Strengths.</strong> {_fmt_list(evaluation.get('strengths'))}</p>"
        f"<p><strong>Improvements.</strong> {_fmt_list(evaluation.get('improvements'))}</p>"
        "<p class='note'>Grammar, vocabulary, and relevance are not a second NLP pipeline; "
        "they live in this judge payload.</p>"
    )
    if answer.speech_metrics is None:
        speech = (
            "<p class='note'>No speech_metrics on this answer "
            "(text-only or transcribe did not succeed). Dual fluency is not invented.</p>"
        )
    else:
        metrics = answer.speech_metrics  # dict
        transcript = f"<p><strong>Transcript.</strong> {_esc(answer.transcript)}</p>"  # Whisper string
        transcript_arm = metrics.get("fluency_transcript") if isinstance(metrics, dict) else None  # ASR-gap
        acoustic_arm = metrics.get("fluency_acoustic") if isinstance(metrics, dict) else None  # Silero
        t_arm = _fluency_dl(transcript_arm, "Fluency (transcript arm)")  # both arms stay visible
        a_arm = _fluency_dl(acoustic_arm, "Fluency (acoustic arm)")  # do not pick a winner
        prosody = metrics.get("prosody") if isinstance(metrics, dict) else None  # pitch / intensity
        if isinstance(prosody, dict):
            proso = (
                "<p><strong>Prosody (not a third fluency score).</strong> "
                f"pitch mean {_esc(prosody.get('pitch_mean_hz'))} Hz, "
                f"intensity mean {_esc(prosody.get('intensity_mean_db'))} dB.</p>"
            )
        else:
            proso = ""  # no Praat block
        speech = transcript + t_arm + a_arm + proso  # both arms visible
    return f"<section class='answer'>{heading}{question}{spoken}{judge}{speech}</section>"  # one card


def build_report_html(ctx: ReportContext) -> str:
    """Return a full HTML document. WeasyPrint renders this string; tests assert on the markup."""
    posting = _esc(ctx.posting_title) if ctx.posting_title else "Practice (no posting)"  # job_id null
    ats = (
        f"<p><strong>ATS (resume).</strong> {_fmt_score(ctx.ats_score)} / 100 "
        f"(stored on the resume; resume_score column is {_fmt_score(ctx.resume_score)}).</p>"
    )
    if isinstance(ctx.ats_breakdown, dict) and ctx.ats_breakdown:
        bits = ", ".join(f"{_esc(k)}={_esc(v)}" for k, v in ctx.ats_breakdown.items())  # section/contact/skill/length
        ats += f"<p class='note'>ATS breakdown: {bits}</p>"  # explainable checklist, not a model
    answers_html = "".join(_answer_section(item) for item in ctx.answers)  # in ask order
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Interview report {_esc(ctx.session_id)}</title>
  <style>
    @page {{ size: A4; margin: 1.6cm; }}
    body {{ font-family: DejaVu Sans, sans-serif; font-size: 11pt; color: #111; }}
    h1 {{ font-size: 18pt; margin: 0 0 0.4em; }}
    h2 {{ font-size: 13pt; margin: 1.2em 0 0.4em; }}
    h3 {{ font-size: 12pt; margin: 1em 0 0.3em; }}
    h4 {{ font-size: 11pt; margin: 0.6em 0 0.2em; }}
    p, li {{ line-height: 1.35; }}
    .note {{ color: #444; font-size: 9.5pt; }}
    table {{ width: 100%; border-collapse: collapse; margin: 0.6em 0; }}
    th, td {{ border: 1px solid #ccc; padding: 0.35em 0.5em; text-align: left; }}
    th {{ background: #f2f2f2; }}
    dl.metrics {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0.15em 1em; }}
    dl.metrics div {{ display: flex; justify-content: space-between; gap: 1em; }}
    section.answer {{ page-break-inside: avoid; margin-bottom: 1em; }}
  </style>
</head>
<body>
  <h1>AI Interview Intelligence Platform — session report</h1>
  <p>Session {_esc(ctx.session_id)} · status {_esc(ctx.status)} · candidate {_esc(ctx.candidate_email)}</p>
  <p>Posting: {posting}. Generated {_esc(ctx.generated_at)} from stored scores (not a live Whisper/Ollama rerun).</p>
  <h2>Composite</h2>
  <p><strong>Composite score:</strong> {_fmt_score(ctx.composite_score)} / 100</p>
  <p>Resume {_fmt_score(ctx.resume_score)} · Technical {_fmt_score(ctx.technical_score)} ·
     Communication {_fmt_score(ctx.communication_score)} · Behavioral {_fmt_score(ctx.behavioral_score)}</p>
  {_signals_table(ctx.attribution)}
  <h2>Resume ATS</h2>
  {ats}
  <h2>Answers</h2>
  {answers_html}
</body>
</html>
"""
