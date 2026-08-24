"""`/resumes/*` endpoints: candidate-only PDF upload (queues parsing) and owner-only results poll.

No ML runs inline here - this router only validates the upload, writes it to local blob storage,
inserts a `resumes` row, and enqueues `resume_parse` via the same `enqueue_job` helper the
job-queue phase built. The ARQ worker (`app/workers/tasks.py::resume_parse`) does the actual
PyMuPDF/spaCy/ESCO/ATS work and writes `parsed_data`/`ats_score` back onto this same row.
"""

import uuid  # path param for GET /resumes/{resume_id}; resume_id also goes into the job payload
from pathlib import Path  # builds the on-disk path under settings.storage_root

from arq.connections import ArqRedis  # injected Redis pool from app.state, same dependency as /jobs
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status  # routing / DI / errors
from sqlalchemy.ext.asyncio import AsyncSession  # request-scoped DB session

from app.auth.dependencies import get_current_user, require_candidate  # upload role guard; any-user for the owner check
from app.core.config import Settings, get_settings  # storage_root: local blob storage filesystem root
from app.core.db import get_db_session  # yields the request-scoped AsyncSession
from app.core.rate_limit import limiter  # slowapi limiter; upload is not free to spam either
from app.models.enums import ResumeStatus  # uploaded -> processing -> parsed/failed
from app.models.resume import Resume  # the row this router creates and later reads back
from app.models.user import User  # type of the authenticated candidate
from app.routers.jobs import get_arq_redis  # reuse the same "is the queue connected" dependency as /jobs
from app.schemas.resumes import ResumeOut, ResumeUploadOut  # request/response contracts
from app.workers.enqueue import EnqueueFailedError, enqueue_job  # insert queued async_jobs row + Redis enqueue
from app.workers.job_types import JOB_TYPE_RESUME_PARSE  # "resume_parse" string job type

router = APIRouter(prefix="/resumes", tags=["resumes"])  # every route here lives under /resumes/...

# Candidates upload a document, not an arbitrary file; PDF-only keeps ml/resume's extractor contract simple.
_ALLOWED_CONTENT_TYPES = {"application/pdf"}
# 10 MiB comfortably covers even a multi-page resume with embedded images while bounding worst-case
# disk/parse cost from an oversized or malicious upload.
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _resume_storage_path(settings: Settings, resume_id: uuid.UUID) -> Path:
    """Where one resume's PDF lives on disk: `<storage_root>/resumes/<resume_id>.pdf`."""
    directory = Path(settings.storage_root) / "resumes"
    directory.mkdir(parents=True, exist_ok=True)  # local dev/test runs may not have this dir yet
    return directory / f"{resume_id}.pdf"


@router.post("", response_model=ResumeUploadOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")  # uploads write to disk + enqueue a job; tighter than the general default
async def upload_resume(
    request: Request,  # required so slowapi can key the limit on client IP
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
    redis: ArqRedis = Depends(get_arq_redis),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(require_candidate),
) -> ResumeUploadOut:
    """Store the uploaded PDF, insert a `resumes` row, enqueue parsing, and return both ids at once."""
    if file.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported content type: {file.content_type!r}; only application/pdf is accepted",
        )

    contents = await file.read()  # resumes are small enough to buffer fully before the size check below
    if not contents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="uploaded file is empty")
    if len(contents) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="file exceeds the 10 MiB upload limit")

    resume = Resume(
        user_id=current_user.id,
        file_path="",  # placeholder; real path needs resume.id, which only exists after flush (see below)
        original_filename=file.filename or "resume.pdf",
        status=ResumeStatus.UPLOADED,
    )
    session.add(resume)
    # UUIDPrimaryKeyMixin's `default=uuid.uuid4` is a column-level default evaluated by SQLAlchemy
    # at flush/INSERT time, not at Python object construction - `resume.id` is None until this flush
    # runs. Reading it any earlier (e.g. to build the storage path) would silently write every
    # upload to the same "None.pdf" file instead of one file per resume.
    await session.flush()
    destination = _resume_storage_path(settings, resume.id)
    resume.file_path = str(destination)
    destination.write_bytes(contents)  # write before commit so a crash never leaves a DB row with no file
    await session.commit()  # worker must see this row before Redis can enqueue (same rule as jobs.enqueue_job)

    try:
        job = await enqueue_job(
            session,
            redis,
            job_type=JOB_TYPE_RESUME_PARSE,
            user_id=current_user.id,
            payload={"resume_id": str(resume.id)},
        )
    except EnqueueFailedError as exc:
        resume.status = ResumeStatus.FAILED  # do not leave a resume stuck "uploaded" if the queue never got it
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="could not enqueue resume parsing",
        ) from exc

    return ResumeUploadOut(resume_id=resume.id, async_job_id=job.id, status=resume.status)


@router.get("/{resume_id}", response_model=ResumeOut)
async def read_resume(
    resume_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> Resume:
    """Return one resume's parsed results if it belongs to the caller; otherwise 404 (not 403).

    Any authenticated role may call this (mirrors `GET /jobs/{id}`'s owner-only-via-404 pattern) -
    a recruiter happens to never own a resume today, so they get the same 404 a mismatched
    candidate would, rather than a role check that would leak "this id belongs to a resume" via a 403.
    """
    resume = await session.get(Resume, resume_id)
    if resume is None or resume.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resume not found")
    return resume
