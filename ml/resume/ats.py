"""A deterministic, explainable ATS (Applicant Tracking System) style score for a parsed resume.

This is intentionally a transparent weighted checklist, not a learned model: recruiters (and the
EU AI Act Article 86 explainability framing referenced in Part 4 of the plan) need to be able to
see exactly why a resume scored what it did, and a resume-pipeline phase has no labeled training
data to fit a model against anyway. `ml/scoring/` (a later phase) is a separate, more general
weighted-aggregation module for the *overall* candidate score across resume/interview/speech
signals - this module only scores the resume document itself.
"""

from dataclasses import dataclass  # typed breakdown so the caller can show per-signal attribution

# Section presence is worth points because ATS-style tools and recruiters both expect a resume to
# be organized into these standard blocks; a resume missing "experience" or "skills" entirely is a
# real ATS-parsing risk in production tools, not just a heuristic quirk here.
_SECTION_POINTS = {
    "experience": 20.0,
    "education": 15.0,
    "skills": 15.0,
    "summary": 5.0,
    "projects": 5.0,
}
_MAX_SECTION_POINTS = sum(_SECTION_POINTS.values())  # 60

_CONTACT_POINTS = 10.0  # email or phone present (5 each, capped at 10)
_SKILL_COUNT_POINTS = 20.0  # scaled by matched-skill count, capped
_SKILL_COUNT_FOR_FULL_POINTS = 8  # matching >= this many taxonomy skills earns full skill points
_LENGTH_POINTS = 10.0  # resumes that are neither near-empty nor absurdly long score better

# A resume shorter than this is almost certainly a parsing failure or a near-empty document.
_MIN_HEALTHY_WORD_COUNT = 80
# Above this, length points taper off (very long resumes are harder for ATS tools and recruiters
# to skim, though this never zeroes the score - it only stops rewarding extra length).
_IDEAL_MAX_WORD_COUNT = 900


@dataclass
class AtsScoreBreakdown:
    """Per-signal points, so a route/response can show the recruiter/candidate *why* the score is X."""

    section_points: float
    contact_points: float
    skill_points: float
    length_points: float
    total: float  # sum of the above, already clamped to [0, 100]


def _word_count(text: str) -> int:
    return len(text.split())


def _length_points(word_count: int) -> float:
    """0 near-empty, ramps to full credit by `_MIN_HEALTHY_WORD_COUNT`, tapers past `_IDEAL_MAX_WORD_COUNT`."""
    if word_count <= 0:
        return 0.0
    if word_count < _MIN_HEALTHY_WORD_COUNT:
        return _LENGTH_POINTS * (word_count / _MIN_HEALTHY_WORD_COUNT)
    if word_count <= _IDEAL_MAX_WORD_COUNT:
        return _LENGTH_POINTS
    # Taper: lose credit gradually for every 500 words past the ideal max, never below half credit.
    overflow_penalty = min((word_count - _IDEAL_MAX_WORD_COUNT) / 500.0, 1.0) * (_LENGTH_POINTS / 2)
    return max(_LENGTH_POINTS - overflow_penalty, _LENGTH_POINTS / 2)


def score_resume(
    *,
    sections: dict[str, str],
    skills: list[str],
    email: str | None,
    phone: str | None,
    raw_text: str,
) -> AtsScoreBreakdown:
    """Compute the 0-100 ATS score plus its breakdown from already-parsed resume data."""
    section_points = sum(points for name, points in _SECTION_POINTS.items() if sections.get(name))
    section_points = min(section_points, _MAX_SECTION_POINTS)

    contact_points = 0.0
    if email:
        contact_points += _CONTACT_POINTS / 2
    if phone:
        contact_points += _CONTACT_POINTS / 2

    skill_ratio = min(len(skills) / _SKILL_COUNT_FOR_FULL_POINTS, 1.0)
    skill_points = _SKILL_COUNT_POINTS * skill_ratio

    length_points = _length_points(_word_count(raw_text))

    total = section_points + contact_points + skill_points + length_points
    total = max(0.0, min(100.0, total))  # clamp defensively even though the components already sum to <= 100

    return AtsScoreBreakdown(
        section_points=round(section_points, 2),
        contact_points=round(contact_points, 2),
        skill_points=round(skill_points, 2),
        length_points=round(length_points, 2),
        total=round(total, 2),
    )
