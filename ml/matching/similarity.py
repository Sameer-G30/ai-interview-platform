"""Vector similarity + skill-gap diffing shared by both the SBERT and TF-IDF matching backends."""

import math  # sqrt for the pure-python cosine fallback path (numpy is still the primary implementation)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors, computed without a hard numpy dependency
    at import time (numpy is already a transitive dependency via spaCy, but keeping this pure-python
    keeps the function trivially unit-testable with plain lists and no fixture setup)."""
    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} != {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0  # a zero vector has no direction; treat as no similarity rather than raising
    return dot / (norm_a * norm_b)


def skill_gap(resume_skills: list[str], required_skills: list[str]) -> tuple[list[str], list[str]]:
    """Case-insensitive set diff between a resume's matched skills and a posting's required skills.

    Both lists are expected to already be ESCO preferred labels from `ml.resume.skills.extract_skills`,
    so equality only needs case-folding, not fuzzy matching. Returns `(matched, missing)`, each sorted
    and de-duplicated, preserving the *required* posting's preferred-label casing in both outputs.
    """
    resume_lookup = {skill.lower() for skill in resume_skills}
    matched: set[str] = set()
    missing: set[str] = set()
    for skill in required_skills:
        if skill.lower() in resume_lookup:
            matched.add(skill)
        else:
            missing.add(skill)
    return sorted(matched), sorted(missing)
