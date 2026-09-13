"""WeasyPrint wrapper around `ml.scoring.build_report_html`. Isolated so ml/ tests never import cairo.

A live PDF smoke / GET /reports skips (or 503s) when WeasyPrint or system cairo/pango cannot be
imported. Do not apt-get from tests. Do not use ReportLab.
"""

from __future__ import annotations  # bytes | None without quotes

from pathlib import Path  # optional cache under storage_root/reports

from ml.scoring import ReportContext, build_report_html  # pure HTML; no WeasyPrint in ml/


def weasyprint_available() -> bool:
    """True when `from weasyprint import HTML` works (cairo/pango present). Never downloads fonts."""
    try:
        from weasyprint import HTML  # noqa: F401  # local import so missing cairo does not break app import
    except Exception:
        return False  # CI without cairo, or a broken system install
    return True  # HTML() can be constructed; write_pdf may still fail later


def render_report_pdf(ctx: ReportContext) -> bytes:
    """Convert the reconstructable HTML into PDF bytes. Raises RuntimeError if WeasyPrint is missing."""
    html = build_report_html(ctx)  # escaped HTML string
    try:
        from weasyprint import HTML  # local import; same reason as weasyprint_available
    except Exception as exc:
        raise RuntimeError("WeasyPrint is not available (cairo/pango missing?)") from exc  # GET maps this to 503
    pdf = HTML(string=html).write_pdf()  # None if called with a target path; we want bytes
    if not pdf:
        raise RuntimeError("WeasyPrint returned an empty PDF")  # should not happen for a full HTML document
    return bytes(pdf)  # ensure a plain bytes object for Response(content=...)


def maybe_cache_pdf(storage_root: str, session_id: str, pdf: bytes) -> Path:
    """Write `<storage_root>/reports/<session_id>.pdf` (gitignored via /data/). Overwrites on each GET."""
    directory = Path(storage_root) / "reports"  # sibling of resumes/ and interviews/
    directory.mkdir(parents=True, exist_ok=True)  # local dev/test may not have this dir yet
    path = directory / f"{session_id}.pdf"  # deterministic name; UUID has no path separators
    path.write_bytes(pdf)  # overwrite; attribution is frozen on the Score row
    return path  # unused by the HTTP response (we stream `pdf` bytes) but handy for debugging
