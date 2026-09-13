"""`GET /reports/{session_id}` streams a WeasyPrint PDF built from stored Score + session rows.

Does not call Ollama or Whisper. Dual fluency is copied from `answers.speech_metrics` into the
HTML (both arms). Blobs may be cached under `<storage_root>/reports/` (gitignored via `/data/`).
"""

import uuid  # path param
from datetime import UTC, datetime  # generated_at stamp on the PDF

from fastapi import APIRouter, Depends, HTTPException, status  # routing / 404 / 503
from fastapi.responses import Response  # application/pdf bytes
from ml.scoring import ReportAnswer, ReportContext  # HTML inputs
from sqlalchemy.ext.asyncio import AsyncSession  # request-scoped DB session

from app.auth.dependencies import get_current_user  # any-auth; ownership is 404
from app.core.config import Settings, get_settings  # storage_root for optional cache
from app.core.db import get_db_session  # request-scoped session
from app.models.job import Job  # optional posting title on the PDF cover
from app.models.resume import Resume  # ATS + breakdown for the PDF
from app.models.user import User  # candidate email + caller
from app.services.pdf_report import maybe_cache_pdf, render_report_pdf, weasyprint_available  # cairo-gated
from app.services.score_access import load_report_session  # owner-only 404

router = APIRouter(prefix="/reports", tags=["reports"])  # GET /reports/{session_id}


@router.get("/{session_id}")
async def download_report(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> Response:
    """PDF for a completed scored session the caller may see. 404 for the wrong id; 503 if WeasyPrint is missing."""
    interview, score = await load_report_session(session, session_id, current_user)  # 404 report not found
    if not weasyprint_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PDF renderer unavailable",
        )  # skippable in tests; do not apt-get
    candidate = await session.get(User, interview.user_id)  # email on the cover
    resume = await session.get(Resume, interview.resume_id)  # ATS
    posting_title = None  # practice sessions have no posting
    if interview.job_id is not None:
        posting = await session.get(Job, interview.job_id)  # may have been deactivated; title still useful
        posting_title = posting.title if posting is not None else None  # None if the posting row vanished
    ats_breakdown = None  # optional checklist
    if resume is not None and isinstance(resume.parsed_data, dict):
        raw = resume.parsed_data.get("ats_breakdown")  # Phase 5 ATS attribution
        ats_breakdown = raw if isinstance(raw, dict) else None  # skip garbage
    answers = [
        ReportAnswer(
            question_order=item.question_order,  # 0-based
            question_kind=item.question_kind,  # technical | behavioral
            is_follow_up=item.is_follow_up,  # probe rows
            question_text=item.question_text,  # generated prompt
            answer_text=item.answer_text,  # submitted text
            evaluation=item.evaluation,  # judge JSON
            transcript=item.transcript,  # Whisper string
            speech_metrics=item.speech_metrics,  # dual fluency; None for text-only
        )
        for item in interview.answers  # already ordered by question_order on the relationship
    ]
    ctx = ReportContext(
        session_id=str(interview.id),  # UUID string in the heading
        status=interview.status.value,  # completed
        candidate_email=candidate.email if candidate is not None else "unknown",  # cover identity
        posting_title=posting_title,  # or Practice
        ats_score=resume.ats_score if resume is not None else None,  # 0–100
        ats_breakdown=ats_breakdown,  # checklist
        resume_score=score.resume_score,  # stored
        technical_score=score.technical_score,  # stored
        communication_score=score.communication_score,  # stored; null on text-only
        behavioral_score=score.behavioral_score,  # stored
        composite_score=score.composite_score,  # stored; do not recompute
        attribution=score.attribution or {},  # reconstructable
        answers=answers,  # per-question
        generated_at=datetime.now(UTC).isoformat(),  # PDF generation time, not completed_at
    )
    try:
        pdf = render_report_pdf(ctx)  # WeasyPrint
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PDF renderer unavailable",
        ) from exc  # missing cairo mid-request
    maybe_cache_pdf(settings.storage_root, str(interview.id), pdf)  # gitignored blob; response still streams memory
    filename = f"interview-report-{interview.id}.pdf"  # Content-Disposition
    return Response(
        content=pdf,  # bytes
        media_type="application/pdf",  # browser download
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},  # thin SPA button uses this
    )
