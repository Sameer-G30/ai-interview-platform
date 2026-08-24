"""ESCO-based skill extraction using spaCy's `PhraseMatcher`.

Part 0 of the plan approved this approach over training a custom NER model: ESCO (the EU's free,
multilingual skills taxonomy) gives broad coverage for free, and `PhraseMatcher` does exact
(case-insensitive) phrase matching against it with no training data or GPU required.

The full ESCO dump is ~13k skills and is deliberately *not* committed to this repo (bloats git
history for a static reference dataset with no test value). Instead this module ships a small
curated sample (`ml/resume/data/esco_skills_sample.json`) that is enough to exercise the pipeline
in tests and local dev, and reads `ESCO_SKILLS_PATH` from the environment so a real deployment can
point at a larger exported file without any code change.
"""

import json  # parses both the bundled sample file and any larger ESCO export pointed at by env
import os  # os.environ.get for the ESCO_SKILLS_PATH override
from functools import lru_cache  # memoize the loaded taxonomy + compiled matcher per process
from pathlib import Path  # bundled sample file path, resolved relative to this module

import spacy  # only used for its Language/PhraseMatcher types in signatures below
from spacy.language import Language  # type of the loaded pipeline passed in by parse.py/tests
from spacy.matcher import PhraseMatcher  # exact multi-word phrase matching, case-insensitive via LOWER attr

# Environment variable a deployment can set to point at a full ESCO export (CSV-with-header-less
# "preferred_label,alias1,alias2,..." rows, or the same JSON shape as the bundled sample) instead
# of the small in-repo sample. Unset in tests/local dev, which is what keeps CI fast and offline.
ESCO_SKILLS_PATH_ENV_VAR = "ESCO_SKILLS_PATH"

# Bundled fallback: a hand-picked ~50-skill sample covering common tech + soft skills, enough to
# make tests and local demos meaningful without shipping the full taxonomy.
_DEFAULT_SKILLS_PATH = Path(__file__).parent / "data" / "esco_skills_sample.json"

# spaCy model used purely for tokenization here (PhraseMatcher needs a Vocab, not the full pipeline);
# parse.py's sectioning also loads this same model name so the two modules stay in lockstep.
DEFAULT_SPACY_MODEL = "en_core_web_sm"


def load_skill_taxonomy(path: str | None = None) -> list[dict]:
    """Load skill entries as a list of `{"preferred_label": str, "aliases": list[str]}` dicts.

    `path` (or `ESCO_SKILLS_PATH` if `path` is None) may point at:
    - the bundled sample JSON shape (`{"skills": [...]}`), or
    - a plain JSON list of the same per-skill dicts (what a larger ESCO export could be converted to).
    Falls back to the bundled sample when neither is set.
    """
    resolved = path or os.environ.get(ESCO_SKILLS_PATH_ENV_VAR) or str(_DEFAULT_SKILLS_PATH)
    with open(resolved, encoding="utf-8") as handle:  # small file; synchronous read is fine even in async workers
        data = json.load(handle)
    # Support both the bundled `{"skills": [...]}` wrapper and a bare list, so a converted ESCO
    # export doesn't need to match our exact wrapper key.
    entries = data["skills"] if isinstance(data, dict) else data
    return [
        {"preferred_label": entry["preferred_label"], "aliases": entry.get("aliases") or [entry["preferred_label"]]}
        for entry in entries
    ]


@lru_cache(maxsize=1)
def _cached_taxonomy_path_and_entries() -> tuple[str, tuple[tuple[str, tuple[str, ...]], ...]]:
    """Cache key is the resolved path so switching `ESCO_SKILLS_PATH` mid-process (tests) reloads."""
    resolved = os.environ.get(ESCO_SKILLS_PATH_ENV_VAR) or str(_DEFAULT_SKILLS_PATH)
    entries = load_skill_taxonomy(resolved)
    frozen = tuple((entry["preferred_label"], tuple(entry["aliases"])) for entry in entries)
    return resolved, frozen


def build_phrase_matcher(nlp: Language) -> tuple[PhraseMatcher, dict[str, str]]:
    """Compile a `PhraseMatcher` over every alias, keyed back to each skill's canonical label.

    Returns `(matcher, label_by_match_key)` where `label_by_match_key` maps the spaCy match string
    (the alias's own `nlp.vocab.strings` key, added as the match id) to the *preferred* label so
    callers can de-duplicate "Python" and "Python3" into a single "Python" result.
    """
    _, entries = _cached_taxonomy_path_and_entries()
    matcher = PhraseMatcher(nlp.vocab, attr="LOWER")  # case-insensitive phrase matching
    label_by_match_key: dict[str, str] = {}
    for preferred_label, aliases in entries:
        for alias in aliases:
            # Registering each alias under its own match id (the alias text) lets us map any hit
            # straight back to its preferred label without a second lookup table keyed by span text.
            matcher.add(alias, [nlp.make_doc(alias)])
            label_by_match_key[alias.lower()] = preferred_label
    return matcher, label_by_match_key


@lru_cache(maxsize=1)
def get_nlp(model_name: str = DEFAULT_SPACY_MODEL) -> Language:
    """Load (and cache) the spaCy pipeline once per process; loading is the expensive part."""
    return spacy.load(model_name)


def extract_skills(text: str, nlp: Language | None = None) -> list[str]:
    """Return the sorted, de-duplicated list of preferred skill labels found in `text`."""
    pipeline = nlp or get_nlp()
    matcher, label_by_match_key = build_phrase_matcher(pipeline)
    doc = pipeline.make_doc(text)  # tokenization only; PhraseMatcher does not need POS/NER
    matches = matcher(doc)
    found: set[str] = set()
    for _match_id, start, end in matches:
        span_text = doc[start:end].text.lower()
        preferred_label = label_by_match_key.get(span_text)
        if preferred_label:
            found.add(preferred_label)
    return sorted(found)
