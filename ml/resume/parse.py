"""PDF text extraction + naive section splitting for uploaded resumes.

Part 0 of the plan approved PyMuPDF as the primary PDF parser (fast, handles most real-world
resume PDFs well) with `pypdfium2` as the documented fallback, since PyMuPDF is AGPL-licensed and
a deployment that cannot accept AGPL can swap to the MIT-licensed fallback by forcing
`use_fallback=True` (or by PyMuPDF failing to open a malformed/encrypted file) with no other code
changes required.
"""

import re  # section-header detection and email/phone regexes used by extract_contact_info
from dataclasses import dataclass, field  # small typed return value instead of an untyped dict

import pymupdf  # primary extractor: fast, handles the vast majority of resume PDFs
import pypdfium2 as pdfium  # MIT fallback extractor if PyMuPDF fails to open/parse a file

# Section headers this heuristic recognizes, lower-cased. A line is treated as a new section
# header when its stripped, lower-cased text exactly matches one of these (short standalone lines
# are how resumes signal sections; this is far cheaper than a trained layout model and is
# sufficient for the ATS-style heuristics in ats.py).
_SECTION_HEADERS = {
    "summary": "summary",
    "objective": "summary",
    "profile": "summary",
    "experience": "experience",
    "work experience": "experience",
    "professional experience": "experience",
    "employment history": "experience",
    "education": "education",
    "academic background": "education",
    "skills": "skills",
    "technical skills": "skills",
    "core competencies": "skills",
    "projects": "projects",
    "personal projects": "projects",
    "certifications": "certifications",
    "certificates": "certifications",
    "awards": "awards",
    "publications": "publications",
    "languages": "languages",
}

# A resume line is only considered a "header line" (as opposed to body text that happens to
# contain one of the words above) when it's short and has no trailing punctuation/sentence shape.
_MAX_HEADER_LINE_LENGTH = 40

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")  # good-enough match for resume contact blocks
_PHONE_RE = re.compile(r"(?:\+?\d[\d\-\s().]{7,}\d)")  # loosely matches +1 555-123-4567 style numbers


@dataclass
class ParsedResume:
    """Structured output of the extraction step, before skill matching / ATS scoring run on it."""

    raw_text: str  # full extracted text, used by skills.extract_skills over the whole document
    sections: dict[str, str] = field(default_factory=dict)  # section name -> concatenated body text
    email: str | None = None  # first email address found, if any
    phone: str | None = None  # first phone-shaped string found, if any
    extractor_used: str = "pymupdf"  # "pymupdf" or "pypdfium2", recorded for debugging bad parses


class ResumeParseError(RuntimeError):
    """Raised when neither PyMuPDF nor the pypdfium2 fallback can extract any text from the file."""


def _extract_text_pymupdf(file_path: str) -> str:
    """Primary extractor. Raises on any pymupdf error so the caller can try the fallback."""
    with pymupdf.open(file_path) as document:
        return "\n".join(page.get_text() for page in document)


def _extract_text_pypdfium2(file_path: str) -> str:
    """MIT-licensed fallback extractor, used when PyMuPDF cannot open/parse the file."""
    pdf = pdfium.PdfDocument(file_path)
    try:
        pages_text = []
        for page in pdf:
            text_page = page.get_textpage()
            try:
                pages_text.append(text_page.get_text_range())
            finally:
                text_page.close()
            page.close()
        return "\n".join(pages_text)
    finally:
        pdf.close()


def extract_text(file_path: str, *, use_fallback: bool = False) -> tuple[str, str]:
    """Return `(text, extractor_used)`. Tries PyMuPDF first unless `use_fallback` forces pypdfium2.

    Falls back to pypdfium2 automatically if PyMuPDF raises (corrupt/encrypted/unsupported PDF),
    so one flaky file does not fail a job that pypdfium2 could have handled.
    """
    if not use_fallback:
        try:
            return _extract_text_pymupdf(file_path), "pymupdf"
        except Exception:  # noqa: BLE001 - any pymupdf failure should try the fallback, not bubble up yet
            pass
    return _extract_text_pypdfium2(file_path), "pypdfium2"


def extract_contact_info(text: str) -> tuple[str | None, str | None]:
    """Return `(email, phone)`, the first match of each found anywhere in the resume text."""
    email_match = _EMAIL_RE.search(text)
    phone_match = _PHONE_RE.search(text)
    return (email_match.group(0) if email_match else None), (phone_match.group(0) if phone_match else None)


def split_into_sections(text: str) -> dict[str, str]:
    """Naive line-based sectioning: short standalone lines matching a known header start a section.

    Text before the first recognized header (contact block, name, headline) is kept under
    "header". This is intentionally simple rather than a trained layout model - resumes are
    short/structured enough that header-line detection covers the common templates, and the ATS
    heuristic in ats.py only needs to know whether a section is *present*, not perfectly delimited.
    """
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line and len(line) <= _MAX_HEADER_LINE_LENGTH:
            normalized = line.lower().strip(":").strip()
            mapped = _SECTION_HEADERS.get(normalized)
            if mapped:
                current = mapped
                sections.setdefault(current, [])
                continue  # header line itself is not part of the section body
        sections.setdefault(current, [])
        sections[current].append(raw_line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items() if "\n".join(lines).strip()}


def parse_resume_file(file_path: str) -> ParsedResume:
    """Run the full extraction step: text, sections, and contact info for one uploaded PDF."""
    text, extractor_used = extract_text(file_path)
    if not text.strip():
        raise ResumeParseError(f"no extractable text in {file_path!r} via pymupdf or pypdfium2")
    email, phone = extract_contact_info(text)
    sections = split_into_sections(text)
    return ParsedResume(raw_text=text, sections=sections, email=email, phone=phone, extractor_used=extractor_used)
