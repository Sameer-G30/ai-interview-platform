"""`/interviews/*` endpoints: candidate-only session start, owner-only GET, text submit, audio blob.

No LLM runs inline here. `POST /interviews` inserts a scheduled session and enqueues
`interview_generate`. `POST .../answers/{id}` stores `answer_text` and enqueues `interview_evaluate`.
`POST .../answers/{id}/audio` writes `audio_path` only (transcript stays null; no Whisper this phase).
The worker calls `ml.llm` inside `asyncio.to_thread`. Poll progress with the existing `GET /jobs/{id}`.
"""

import uuid  # path params for session_id / answer_id; resume_id / job_id in the start body
from pathlib import Path  # builds the on-disk path under settings.storage_root

from arq.connections import ArqRedis  # injected Redis pool from app.state
from fastapi import (  # routing / DI / errors / multipart audio
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import select  # session GET with selectinload of answers
from sqlalchemy.ext.asyncio import AsyncSession  # request-scoped DB session
from sqlalchemy.orm import selectinload  # eager-load answers so GET does not lazy-IO in async

from app.auth.dependencies import (  # start/submit/audio are candidate-only; GET is any-auth 404
    get_current_user,
    require_candidate,
)
from app.core.config import Settings, get_settings  # storage_root for MediaRecorder blobs
from app.core.db import get_db_session  # yields the request-scoped AsyncSession
from app.core.rate_limit import limiter  # slowapi limiter; start/submit enqueue jobs
from app.models.answer import Answer  # submit/audio target; generate worker inserts these
from app.models.enums import InterviewSessionStatus  # scheduled / in_progress / completed / abandoned
from app.models.interview_session import InterviewSession  # the row this router creates and reads
from app.models.job import Job  # optional posting looked up by body.job_id
from app.models.user import User  # type of the authenticated caller
from app.routers.jobs import get_arq_redis  # reuse the same "is the queue connected" dependency as /jobs
from app.schemas.interviews import (  # request/response contracts
    AnswerSubmitIn,
    AnswerSubmitOut,
    AudioUploadOut,
    InterviewSessionOut,
    InterviewStartIn,
    InterviewStartOut,
)
from app.services.resume_selection import resolve_parsed_resume  # same 404/409 rules as GET /matches
from app.workers.enqueue import EnqueueFailedError, enqueue_job  # insert queued async_jobs row + Redis enqueue
from app.workers.job_types import JOB_TYPE_INTERVIEW_EVALUATE, JOB_TYPE_INTERVIEW_GENERATE  # plain string job types

router = APIRouter(prefix="/interviews", tags=["interviews"])  # every route here lives under /interviews/...

# Chromium MediaRecorder with audio/webm;codecs=opus typically reports audio/webm; some builds use video/webm.
_ALLOWED_AUDIO_TYPES = {"audio/webm", "video/webm"}
# 10 MiB matches resume uploads; Opus at ~32 kbps is far smaller than this for a typical spoken answer.
_MAX_AUDIO_BYTES = 10 * 1024 * 1024


def _normalize_content_type(content_type: str | None) -> str:
    """Strip codec parameters so `audio/webm;codecs=opus` matches the allow-list as `audio/webm`."""
    raw = (content_type or "").split(";", 1)[0].strip().lower()  # "audio/webm;codecs=opus" -> "audio/webm"
    return raw


def _audio_storage_path(settings: Settings, session_id: uuid.UUID, answer_id: uuid.UUID) -> Path:
    """Where one answer's WebM lives: `<storage_root>/interviews/<session_id>/<answer_id>.webm`."""
    directory = Path(settings.storage_root) / "interviews" / str(session_id)  # one folder per session
    directory.mkdir(parents=True, exist_ok=True)  # local dev/test runs may not have this dir yet
    return directory / f"{answer_id}.webm"  # overwrite on retry; same path as a previous upload


async def _resolve_optional_posting(session: AsyncSession, job_id: uuid.UUID | None) -> Job | None:
    """Return the posting when `job_id` is set: 404 if missing, 409 if inactive. None when omitted."""
    if job_id is None:
        return None  # practice interview: generate from resume skills only
    posting = await session.get(Job, job_id)
    if posting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="posting not found")
    if not posting.is_active:
        # Distinct from "not found": the id is valid, the recruiter just closed the posting.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="posting is not active")
    return posting


@router.post("", response_model=InterviewStartOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("30/minute")  # start writes a session row + enqueues LLM work; 30 leaves room for the pytest suite
async def start_interview(
    request: Request,  # required so slowapi can key the limit on client IP
    body: InterviewStartIn,
    session: AsyncSession = Depends(get_db_session),
    redis: ArqRedis = Depends(get_arq_redis),
    current_user: User = Depends(require_candidate),
) -> InterviewStartOut:
    """Insert a scheduled session from an owned parsed resume (and optional posting) and enqueue generation."""
    resume = await resolve_parsed_resume(session, current_user, body.resume_id)  # 404/409, never 403 for ownership
    posting = await _resolve_optional_posting(session, body.job_id)  # None when job_id omitted
    interview = InterviewSession(
        user_id=current_user.id,
        resume_id=resume.id,
        job_id=posting.id if posting is not None else None,
        status=InterviewSessionStatus.SCHEDULED,  # worker flips this to in_progress once questions exist
    )
    session.add(interview)
    await session.flush()  # UUID mixin default assigns id in Python; flush still makes the INSERT visible to commit
    await session.commit()  # worker must see this row before Redis can enqueue (same rule as resume upload)

    try:
        job = await enqueue_job(
            session,
            redis,
            job_type=JOB_TYPE_INTERVIEW_GENERATE,
            user_id=current_user.id,
            payload={"session_id": str(interview.id)},
        )
    except EnqueueFailedError as exc:
        interview.status = InterviewSessionStatus.ABANDONED  # do not leave a session stuck scheduled with no job
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="could not enqueue question generation",
        ) from exc

    return InterviewStartOut(session_id=interview.id, async_job_id=job.id, status=interview.status)


@router.get("/{session_id}", response_model=InterviewSessionOut)
async def read_interview(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> InterviewSession:
    """Return one session if it belongs to the caller; otherwise 404 (not 403) so ids are not enumerable.

    Any authenticated role may call this (mirrors GET /jobs/{id} and GET /resumes/{id}). A recruiter
    never owns a session today, so they get the same 404 a mismatched candidate would.
    """
    result = await session.execute(
        select(InterviewSession)
        .options(selectinload(InterviewSession.answers))  # answers.question_order order comes from the relationship
        .where(InterviewSession.id == session_id)
    )
    interview = result.scalar_one_or_none()
    if interview is None or interview.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    return interview


@router.post("/{session_id}/answers/{answer_id}", response_model=AnswerSubmitOut)
@limiter.limit("20/minute")  # each submit enqueues an evaluate job; still cheaper than start
async def submit_answer(
    request: Request,  # required so slowapi can key the limit on client IP
    session_id: uuid.UUID,
    answer_id: uuid.UUID,
    body: AnswerSubmitIn,
    session: AsyncSession = Depends(get_db_session),
    redis: ArqRedis = Depends(get_arq_redis),
    current_user: User = Depends(require_candidate),
) -> AnswerSubmitOut:
    """Store a text answer and enqueue evaluation. Audio is a separate POST .../audio; transcript stays NULL."""
    interview = await session.get(InterviewSession, session_id)
    if interview is None or interview.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    if interview.status in {InterviewSessionStatus.COMPLETED, InterviewSessionStatus.ABANDONED}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="session is not accepting answers")
    answer = await session.get(Answer, answer_id)
    if answer is None or answer.session_id != interview.id:
        # Missing or belonging to another session: 404, not 403, so answer ids are not enumerable.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="answer not found")
    if answer.answer_text is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="answer already submitted")
    answer.answer_text = body.answer_text  # worker reads this; audio_path/transcript stay null
    await session.commit()  # evaluate worker must see answer_text before Redis has the message

    try:
        job = await enqueue_job(
            session,
            redis,
            job_type=JOB_TYPE_INTERVIEW_EVALUATE,
            user_id=current_user.id,
            payload={"answer_id": str(answer.id), "session_id": str(interview.id)},
        )
    except EnqueueFailedError as exc:
        answer.answer_text = None  # unlock so the candidate can retry submit after a queue outage
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="could not enqueue answer evaluation",
        ) from exc

    return AnswerSubmitOut(answer_id=answer.id, async_job_id=job.id, session_status=interview.status)


@router.post("/{session_id}/answers/{answer_id}/audio", response_model=AudioUploadOut)
@limiter.limit("20/minute")  # disk write + possible overwrite; same bucket as text submit
async def upload_answer_audio(
    request: Request,  # required so slowapi can key the limit on client IP
    session_id: uuid.UUID,
    answer_id: uuid.UUID,
    file: UploadFile = File(...),  # multipart field name is `file`, matching POST /resumes
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(require_candidate),
) -> AudioUploadOut:
    """Store a Chromium MediaRecorder WebM blob on `audio_path`. Does not enqueue evaluate or run Whisper.

    Text submit remains the only path that queues `interview_evaluate` (the judge needs `answer_text`).
    Transcript stays NULL until Phase 11. Retry overwrites the same file. Abandoned sessions 409.
    """
    interview = await session.get(InterviewSession, session_id)
    if interview is None or interview.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
    if interview.status == InterviewSessionStatus.ABANDONED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="session is not accepting answers")
    answer = await session.get(Answer, answer_id)
    if answer is None or answer.session_id != interview.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="answer not found")

    content_type = _normalize_content_type(file.content_type)
    if content_type not in _ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported content type: {file.content_type!r}; only audio/webm is accepted",
        )

    contents = await file.read()  # spoken answers are small enough to buffer fully before the size check
    if not contents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="uploaded file is empty")
    if len(contents) > _MAX_AUDIO_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file exceeds the 10 MiB upload limit")

    destination = _audio_storage_path(settings, interview.id, answer.id)
    destination.write_bytes(contents)  # overwrite on retry so a second capture replaces the first blob
    answer.audio_path = str(destination)  # Phase 11 Whisper will read this; transcript stays null
    await session.commit()  # persist the path; no ARQ job — audio is storage only this phase
    return AudioUploadOut(answer_id=answer.id, has_audio=True)
