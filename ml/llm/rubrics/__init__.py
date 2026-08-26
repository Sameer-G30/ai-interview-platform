"""Load versioned rubric prompt files from this package directory.

Rubrics live as markdown files (`{name}_v{version}.md`) so a wording bump is a new file, not a
backend change. `OllamaBackend` / `OpenAICompatBackend` never import these strings; they only see
the `messages` list the caller built after `load_rubric(...)`.
"""

from pathlib import Path  # resolve files next to this module, matching ml.resume.skills's sample-data pattern

from ml.llm.errors import RubricNotFoundError  # typed miss so callers do not catch bare FileNotFoundError

_RUBRICS_DIR = Path(__file__).resolve().parent  # directory that contains this __init__.py and the *.md files

_FILENAME_PATTERN = "{name}_v{version}.md"  # stable template; bumping v1 -> v2 is a new file with this shape


def rubric_path(name: str, version: int) -> Path:
    """Return the path for one rubric file without reading it (useful for tests asserting the layout)."""
    return _RUBRICS_DIR / _FILENAME_PATTERN.format(name=name, version=version)  # e.g. technical_answer_v1.md


def load_rubric(name: str, version: int = 1) -> str:
    """Return the markdown body of `{name}_v{version}.md`.

    Raises `RubricNotFoundError` when the file is missing so a typo in Phase 9 does not silently
    fall back to an older prompt baked into a backend.
    """
    path = rubric_path(name, version)  # resolve against this package dir, not the process cwd
    if not path.is_file():  # missing version is a caller error, not a backend error
        raise RubricNotFoundError(f"rubric not found: {name!r} version {version} ({path.name})")
    return path.read_text(encoding="utf-8")  # prompts are UTF-8 markdown; keep newlines intact


def list_rubrics() -> list[tuple[str, int]]:
    """Return `(name, version)` for every `*_vN.md` file in this directory, sorted for stable tests."""
    found: list[tuple[str, int]] = []  # accumulate then sort so callers do not depend on filesystem order
    for path in _RUBRICS_DIR.glob("*_v*.md"):  # ignore __init__.py and any non-rubric notes
        stem = path.stem  # filename without .md, e.g. technical_answer_v1
        if "_v" not in stem:  # defensive: glob is already tight, but skip odd names
            continue  # pragma: no cover - glob already requires `_v`
        name, _, version_str = stem.rpartition("_v")  # split on the last `_v` so names may contain underscores
        if not name or not version_str.isdigit():  # skip files that do not match `{name}_v{int}`
            continue  # e.g. a future README_vnotes.md would be ignored rather than crashing
        found.append((name, int(version_str)))  # version is the integer after `_v`
    found.sort()  # (name, version) lexicographic then numeric-as-int via the tuple
    return found  # empty only if every rubric file was deleted, which tests would catch
