"""Owner-only lookup for a session's stored Score / PDF. 404 (not 403) for the wrong id.

Candidates may read their own session. Recruiters may read a session only when `job_id` points at
a posting they own. Practice sessions (job_id null) are never visible to recruiters. Missing Score
rows (in_progress / abandoned / completed before Phase 13) are also 404.
"""

import uuid  # session_id path params

from fastapi import HTTPException, status  # 404 hides whether the id exists
from sqlalchemy import select  # Score lookup by session_id
from sqlalchemy.ext.asyncio import AsyncSession  # request-scoped or worker session
from sqlalchemy.orm import selectinload  # eager-load answers when the PDF needs them

from app.models.enums import UserRole  # candidate vs recruiter branch
from app.models.interview_session import InterviewSession  # parent of Score
from app.models.job import Job  # posting ownership for recruiters
from app.models.score import Score  # one row per completed session
from app.models.user import User  # authenticated caller


def _not_found(detail: str) -> HTTPException:
    """Build a 404 so ids are not enumerable (same convention as GET /jobs/{id})."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)  # never 403 for ownership


async def session_visible_to(db: AsyncSession, session_id: uuid.UUID, current_user: User) -> InterviewSession:
    """Return the session if the caller may see its score/report; otherwise 404.

    Does not require a Score row (the report/score routes check that separately so the detail
    string can stay 'score not found' / 'report not found').
    """
    interview = await db.get(InterviewSession, session_id)  # None if the UUID was never inserted
    if interview is None:
        raise _not_found("session not found")  # same wording for missing and unauthorized below
    if current_user.role == UserRole.CANDIDATE:
        if interview.user_id != current_user.id:
            raise _not_found("session not found")  # other candidate's id
        return interview  # practice or posting-targeted; both are the candidate's own
    if current_user.role == UserRole.RECRUITER:
        if interview.job_id is None:
            raise _not_found("session not found")  # practice interviews are not recruiter-visible
        posting = await db.get(Job, interview.job_id)
        if posting is None or posting.recruiter_id != current_user.id:
            raise _not_found("session not found")  # other recruiter's posting, or the posting vanished
        return interview  # tied to a posting this recruiter owns
    raise _not_found("session not found")  # no other roles exist


async def load_score_for_user(
    db: AsyncSession, session_id: uuid.UUID, current_user: User
) -> tuple[InterviewSession, Score]:
    """Session + Score row the caller may read. 404 if the session is hidden or has no Score yet."""
    interview = await session_visible_to(db, session_id, current_user)  # 404 if not allowed
    score = await db.scalar(select(Score).where(Score.session_id == interview.id))  # unique session_id
    if score is None or score.composite_score is None:
        raise _not_found("score not found")  # in_progress / abandoned / failed aggregation
    return interview, score  # both loaded; caller serializes ScoreOut


async def load_report_session(
    db: AsyncSession, session_id: uuid.UUID, current_user: User
) -> tuple[InterviewSession, Score]:
    """Like load_score_for_user but eager-loads answers for the PDF and 404s with 'report not found'."""
    interview = await session_visible_to(db, session_id, current_user)  # role/ownership 404
    loaded = await db.scalar(
        select(InterviewSession)
        .options(selectinload(InterviewSession.answers))  # PDF iterates questions
        .where(InterviewSession.id == interview.id)
    )
    if loaded is None:
        raise _not_found("report not found")  # should not happen after session_visible_to
    score = await db.scalar(select(Score).where(Score.session_id == loaded.id))  # unique
    if score is None or score.composite_score is None:
        raise _not_found("report not found")  # no composite yet
    return loaded, score  # answers already selectinloaded
