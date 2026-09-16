"""`/admin/*` endpoints: user/posting management plus audit listing of sessions and scores.

All routes use `require_admin` (recruiter AND `is_admin=True` → else 403; unauthenticated 401).
Missing ids are 404, not 403, matching GET /jobs/{id}. Recruiters without the flag never see
cross-recruiter data from GET /postings — that list stays own-only. Admin session/score listing
includes practice (`job_id` null); recruiter ranking does not. GET never recomputes composites.
"""

import uuid  # path params for user / posting / session ids

from fastapi import APIRouter, Depends, HTTPException, Query, status  # routing / DI / 404 / 422
from sqlalchemy import select  # listing queries
from sqlalchemy.ext.asyncio import AsyncSession  # request-scoped DB session
from sqlalchemy.orm import joinedload  # session list joins job + score + user

from app.auth.dependencies import require_admin  # recruiter + is_admin; everyone else is 403
from app.core.db import get_db_session  # yields the request-scoped AsyncSession
from app.models.enums import InterviewSessionStatus, UserRole  # query filters + PATCH guards
from app.models.interview_session import InterviewSession  # audit listing
from app.models.job import Job  # cross-recruiter posting list
from app.models.score import Score  # stored composites; GET does not call ml.scoring
from app.models.user import User  # list + PATCH is_active / is_admin
from app.schemas.admin import (  # admin JSON contracts
    AdminPostingOut,
    AdminScoreListItemOut,
    AdminSessionListItemOut,
    AdminUserPatch,
)
from app.schemas.auth import UserOut  # same public user shape as GET /auth/me (no password hash)
from app.schemas.postings import PostingUpdate  # PATCH is_active only; no hard delete

router = APIRouter(prefix="/admin", tags=["admin"])  # one HTTP prefix; Vite proxies /admin the same way


def _not_found(detail: str) -> HTTPException:
    """404 so unknown UUIDs are not distinguishable from 'exists but hidden' on other routers."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)  # never 403 for a missing id


def _session_item(interview: InterviewSession) -> AdminSessionListItemOut:
    """Map one ORM session (user/job/score already loaded) onto the audit-list contract."""
    posting = interview.job  # joinedload; None for practice or ON DELETE SET NULL
    score = interview.score  # joinedload; None until evaluate writes a completed composite
    candidate = interview.user  # joinedload; always present (FK CASCADE)
    return AdminSessionListItemOut(
        id=interview.id,  # ops table key
        candidate_user_id=candidate.id,  # users.id
        candidate_email=candidate.email,  # identifiable without a second GET
        resume_id=interview.resume_id,  # parsed resume used to generate questions
        job_id=interview.job_id,  # null = practice; still listed for admin
        posting_title=posting.title if posting is not None else None,  # display
        status=interview.status,  # scheduled | in_progress | completed | abandoned
        started_at=interview.started_at,  # None while still scheduled
        completed_at=interview.completed_at,  # None until evaluate completes the session
        created_at=interview.created_at,  # sort key (newest first)
        updated_at=interview.updated_at,  # last write
        composite_score=score.composite_score if score is not None else None,  # stored; not recomputed
    )


@router.get("/users", response_model=list[UserOut])
async def list_users(
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(require_admin),
    role: UserRole | None = Query(default=None, description="Optional role filter"),
    is_active: bool | None = Query(default=None, description="Optional active-flag filter"),
) -> list[User]:
    """List accounts newest `created_at` first. Soft-disabled rows stay here (`is_active=false`)."""
    stmt = select(User).order_by(User.created_at.desc())  # newest first, matching other collections
    if role is not None:
        stmt = stmt.where(User.role == role)  # candidate | recruiter; there is no UserRole.ADMIN
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)  # deactivated accounts remain listable
    result = await session.execute(stmt)  # live Postgres
    return list(result.scalars().all())  # UserOut serializes without hashed_password


@router.get("/users/{user_id}", response_model=UserOut)
async def read_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(require_admin),
) -> User:
    """Return one user by id. Unknown UUID is 404 (not 403)."""
    user = await session.get(User, user_id)  # None if the UUID was never inserted
    if user is None:
        raise _not_found("user not found")  # same wording whether missing or (n/a) unauthorized
    return user  # UserOut


@router.patch("/users/{user_id}", response_model=UserOut)
async def patch_user(
    user_id: uuid.UUID,
    body: AdminUserPatch,
    session: AsyncSession = Depends(get_db_session),
    current_admin: User = Depends(require_admin),
) -> User:
    """Soft-disable via `is_active`, or toggle `is_admin` on recruiters only. No hard DELETE.

    Deactivate does not bulk-revoke refresh token rows: `get_current_user` already 401s when
    `is_active` is false, and `rotate_refresh_token` already refuses inactive accounts. Do not
    invent a second auth stack. Force-revoke-all on deactivate is an explicit follow-up.
    """
    if body.is_active is None and body.is_admin is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="provide is_active and/or is_admin",
        )
    user = await session.get(User, user_id)  # None if unknown
    if user is None:
        raise _not_found("user not found")  # unknown UUID
    if user.id == current_admin.id and body.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cannot deactivate your own account",
        )
    if user.id == current_admin.id and body.is_admin is False:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="cannot remove your own admin flag",
        )
    if body.is_admin is not None:
        if user.role != UserRole.RECRUITER:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="is_admin can only be set on recruiters",
            )
        user.is_admin = body.is_admin  # never settable via POST /auth/register
    if body.is_active is not None:
        user.is_active = body.is_active  # False = soft disable; True = re-enable
    await session.commit()  # persist
    await session.refresh(user)  # return the stored row
    return user  # UserOut


@router.get("/postings", response_model=list[AdminPostingOut])
async def list_postings(
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(require_admin),
    recruiter_id: uuid.UUID | None = Query(default=None, description="Optional owner filter"),
    is_active: bool | None = Query(default=None, description="Optional active-flag filter"),
) -> list[AdminPostingOut]:
    """List every recruiter's postings, newest first. Do not widen GET /postings for this."""
    stmt = (
        select(Job, User)
        .join(User, User.id == Job.recruiter_id)  # owner email for the table
        .order_by(Job.created_at.desc())  # newest first
    )
    if recruiter_id is not None:
        stmt = stmt.where(Job.recruiter_id == recruiter_id)  # one recruiter's jobs
    if is_active is not None:
        stmt = stmt.where(Job.is_active == is_active)  # active / inactive
    result = await session.execute(stmt)  # live Postgres
    return [AdminPostingOut.from_job(job, recruiter) for job, recruiter in result.all()]  # embedding derived


@router.get("/postings/{posting_id}", response_model=AdminPostingOut)
async def read_posting(
    posting_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(require_admin),
) -> AdminPostingOut:
    """Return one posting from any recruiter. Unknown UUID is 404. Does not collide with GET /jobs/{id}."""
    job = await session.get(Job, posting_id)  # None if never a posting
    if job is None:
        raise _not_found("posting not found")  # not 403
    recruiter = await session.get(User, job.recruiter_id)  # FK CASCADE so this should exist
    if recruiter is None:
        raise _not_found("posting not found")  # defensive; owner vanished
    return AdminPostingOut.from_job(job, recruiter)  # same shape as the list row


@router.patch("/postings/{posting_id}", response_model=AdminPostingOut)
async def patch_posting(
    posting_id: uuid.UUID,
    body: PostingUpdate,
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(require_admin),
) -> AdminPostingOut:
    """Flip `is_active` on any recruiter's posting. No hard delete. Same body as owner PATCH /postings/{id}."""
    job = await session.get(Job, posting_id)  # None if unknown
    if job is None:
        raise _not_found("posting not found")  # unknown UUID
    job.is_active = body.is_active  # prefer is_active over DELETE
    await session.commit()  # persist
    await session.refresh(job)  # return stored row
    recruiter = await session.get(User, job.recruiter_id)  # owner email
    if recruiter is None:
        raise _not_found("posting not found")  # defensive
    return AdminPostingOut.from_job(job, recruiter)  # derived has_embedding


@router.get("/sessions", response_model=list[AdminSessionListItemOut])
async def list_sessions(
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(require_admin),
    session_status: InterviewSessionStatus | None = Query(
        default=None,
        alias="status",
        description="Optional session-status filter",
    ),
    user_id: uuid.UUID | None = Query(default=None, description="Optional candidate user id"),
) -> list[AdminSessionListItemOut]:
    """List every session including practice, newest `created_at` first. Not GET /interviews (that is own-only)."""
    stmt = (
        select(InterviewSession)
        .options(
            joinedload(InterviewSession.job),  # posting_title
            joinedload(InterviewSession.score),  # stored composite; do not recompute
            joinedload(InterviewSession.user),  # candidate email
        )
        .order_by(InterviewSession.created_at.desc())  # newest first
    )
    if session_status is not None:
        stmt = stmt.where(InterviewSession.status == session_status)  # scheduled / in_progress / completed / abandoned
    if user_id is not None:
        stmt = stmt.where(InterviewSession.user_id == user_id)  # one candidate's history
    result = await session.execute(stmt)  # live Postgres
    return [_session_item(interview) for interview in result.scalars().unique().all()]  # unique() for joinedload


@router.get("/sessions/{session_id}", response_model=AdminSessionListItemOut)
async def read_session(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(require_admin),
) -> AdminSessionListItemOut:
    """Return one session (practice included). Unknown UUID is 404. Does not return the answers array."""
    interview = await session.scalar(
        select(InterviewSession)
        .options(
            joinedload(InterviewSession.job),  # posting_title
            joinedload(InterviewSession.score),  # stored composite
            joinedload(InterviewSession.user),  # candidate email
        )
        .where(InterviewSession.id == session_id)  # primary key
    )
    if interview is None:
        raise _not_found("session not found")  # unknown UUID
    return _session_item(interview)  # slim audit row


@router.get("/scores", response_model=list[AdminScoreListItemOut])
async def list_scores(
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(require_admin),
) -> list[AdminScoreListItemOut]:
    """List stored Score rows (composite present), practice included. Does not call `aggregate_session`."""
    result = await session.execute(
        select(Score, InterviewSession, User, Job)
        .join(InterviewSession, InterviewSession.id == Score.session_id)  # parent session
        .join(User, User.id == InterviewSession.user_id)  # candidate identity
        .outerjoin(Job, Job.id == InterviewSession.job_id)  # posting title; null for practice
        .where(Score.composite_score.is_not(None))  # in_progress / abandoned have no composite
        .order_by(InterviewSession.completed_at.desc().nulls_last(), Score.created_at.desc())  # newest completed first
    )
    rows: list[AdminScoreListItemOut] = []  # build JSON
    for score, interview, candidate, posting in result.all():
        rows.append(
            AdminScoreListItemOut(
                session_id=score.session_id,  # GET /admin/scores/{id} target
                candidate_user_id=candidate.id,  # users.id
                candidate_email=candidate.email,  # display
                job_id=interview.job_id,  # null = practice
                posting_title=posting.title if posting is not None else None,  # display
                resume_score=score.resume_score,  # stored
                technical_score=score.technical_score,  # stored
                communication_score=score.communication_score,  # null on text-only
                behavioral_score=score.behavioral_score,  # stored
                composite_score=score.composite_score,  # stored; not recomputed
                attribution=score.attribution,  # reconstructable
                completed_at=interview.completed_at,  # when evaluate flipped the session
            )
        )
    return rows  # empty list is a valid 200


@router.get("/scores/{session_id}", response_model=AdminScoreListItemOut)
async def read_score(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    _admin: User = Depends(require_admin),
) -> AdminScoreListItemOut:
    """Return one stored Score. Practice is visible. 404 if missing or composite is still null."""
    row = await session.execute(
        select(Score, InterviewSession, User, Job)
        .join(InterviewSession, InterviewSession.id == Score.session_id)  # parent
        .join(User, User.id == InterviewSession.user_id)  # candidate
        .outerjoin(Job, Job.id == InterviewSession.job_id)  # posting may be null
        .where(Score.session_id == session_id, Score.composite_score.is_not(None))  # stored composite only
    )
    packed = row.first()  # one row or None
    if packed is None:
        raise _not_found("score not found")  # unknown UUID, in_progress, or abandoned
    score, interview, candidate, posting = packed  # unpack
    return AdminScoreListItemOut(
        session_id=score.session_id,  # UUID
        candidate_user_id=candidate.id,  # users.id
        candidate_email=candidate.email,  # display
        job_id=interview.job_id,  # null = practice
        posting_title=posting.title if posting is not None else None,  # display
        resume_score=score.resume_score,  # stored
        technical_score=score.technical_score,  # stored
        communication_score=score.communication_score,  # omitted stays null
        behavioral_score=score.behavioral_score,  # stored
        composite_score=score.composite_score,  # stored
        attribution=score.attribution,  # reconstructable
        completed_at=interview.completed_at,  # timestamp
    )
