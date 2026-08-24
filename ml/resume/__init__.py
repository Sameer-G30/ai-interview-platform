"""Resume pipeline: PyMuPDF/pypdfium2 text extraction, spaCy sectioning, ESCO skill matching, ATS score.

`run_resume_pipeline` is the single entry point the ARQ worker (and, later, the research harness)
calls; it exists here rather than duplicated per-module so both callers exercise the exact same
code path per the plan's instrumentation requirement.
"""

from dataclasses import asdict  # convert the ATS breakdown dataclass to a JSON-safe dict

from ml.resume.ats import score_resume  # deterministic ATS scoring over parsed sections/skills
from ml.resume.parse import ResumeParseError, parse_resume_file  # PDF -> text/sections/contact info
from ml.resume.skills import extract_skills  # ESCO PhraseMatcher over the raw resume text

__all__ = ["ResumeParseError", "run_resume_pipeline"]


def run_resume_pipeline(file_path: str) -> tuple[dict, float]:
    """Parse one resume PDF end to end.

    Returns `(parsed_data, ats_score)` where `parsed_data` is the JSON-serializable dict written to
    `Resume.parsed_data` and `ats_score` is the float written to `Resume.ats_score`. Raises
    `ResumeParseError` if no text could be extracted at all (caller/worker turns this into a
    `failed` resume + async job, per the existing `run_tracked_job` convention).
    """
    parsed = parse_resume_file(file_path)  # may raise ResumeParseError; let the worker catch it
    skills = extract_skills(parsed.raw_text)
    breakdown = score_resume(
        sections=parsed.sections,
        skills=skills,
        email=parsed.email,
        phone=parsed.phone,
        raw_text=parsed.raw_text,
    )
    parsed_data = {
        "sections": parsed.sections,
        "skills": skills,
        "email": parsed.email,
        "phone": parsed.phone,
        "extractor_used": parsed.extractor_used,
        "ats_breakdown": asdict(breakdown),
        "word_count": len(parsed.raw_text.split()),
    }
    return parsed_data, breakdown.total
