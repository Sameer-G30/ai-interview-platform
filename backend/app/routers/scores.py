"""`/scores/*` endpoints: owner GET, recruiter ranking by posting, recruiter comparison.

Aggregation is arithmetic and already stored on `scores` when a session completes. These handlers
only read; they do not call Ollama, Whisper, or `aggregate_session`. Candidate history is
`GET /interviews` (own rows only). Recruiter ranking/compare stay on this router.
"""

import uuid  # path and query params

from fastapi import APIRouter, Depends, HTTPException, Query, status  # routing / DI / 404
from sqlalchemy import select  # ranking join
from sqlalchemy.ext.asyncio import AsyncSession  # request-scoped DB session

from app.auth.dependencies import get_current_user, require_recruiter  # GET score is any-auth; rank/compare recruiter
from app.core.db import get_db_session  # yields the request-scoped AsyncSession
from app.models.enums import InterviewSessionStatus  # ranking only includes completed sessions
from app.models.interview_session import InterviewSession  # job_id ties a session to a posting
from app.models.job import Job  # posting ownership
from app.models.score import Score  # stored composite
from app.models.user import User  # candidate email on ranking rows
from app.schemas.scores import ComparisonOut, RankingOut, RankingRowOut, ScoreOut  # JSON contracts
from app.services.score_access import load_score_for_user  # owner-only 404 helper

router = APIRouter(prefix="/scores", tags=["scores"])  # every route here lives under /scores/...


def _score_out(score: Score) -> ScoreOut:
    """Map the ORM row onto the snake_case JSON contract."""
    return ScoreOut(
        session_id=score.session_id,  # UUID
        resume_score=score.resume_score,  # may be null
        technical_score=score.technical_score,  # may be null
        communication_score=score.communication_score,  # null on text-only
        behavioral_score=score.behavioral_score,  # may be null
        composite_score=score.composite_score,  # GET 404s when this is still null
        attribution=score.attribution,  # reconstructable JSON
    )


@router.get("/rankings", response_model=RankingOut)
async def rank_posting_sessions(
    posting_id: uuid.UUID = Query(..., description="Posting (jobs.id) the recruiter owns"),
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_recruiter),
) -> RankingOut:
    """Completed sessions on one owned posting, highest composite_score first. 404 if posting is not owned."""
    posting = await session.get(Job, posting_id)  # None if the UUID was never a posting
    if posting is None or posting.recruiter_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="posting not found")  # not 403
    result = await session.execute(
        select(InterviewSession, Score, User)
        .join(Score, Score.session_id == InterviewSession.id)  # inner join: no score → not ranked
        .join(User, User.id == InterviewSession.user_id)  # candidate identity for curl
        .where(
            InterviewSession.job_id == posting_id,  # tied to this posting (practice sessions have job_id null)
            InterviewSession.status == InterviewSessionStatus.COMPLETED,  # abandoned never ranked
            Score.composite_score.is_not(None),  # do not rank a row that failed to aggregate
        )
        .order_by(Score.composite_score.desc(), InterviewSession.completed_at.asc())  # stable tie-break
    )
    rows: list[RankingRowOut] = []  # 1-based rank
    for rank, (interview, score, candidate) in enumerate(result.all(), start=1):
        rows.append(
            RankingRowOut(
                rank=rank,  # 1 is the highest composite
                session_id=interview.id,  # PDF / GET score target
                candidate_user_id=candidate.id,  # users.id
                candidate_email=candidate.email,  # identifiable without a dashboard
                completed_at=interview.completed_at,  # when evaluate flipped the session
                resume_score=score.resume_score,  # echo
                technical_score=score.technical_score,  # echo
                communication_score=score.communication_score,  # echo
                behavioral_score=score.behavioral_score,  # echo
                composite_score=score.composite_score,  # sort key
                attribution=score.attribution,  # reconstructable
            )
        )
    return RankingOut(posting_id=posting_id, sessions=rows)  # empty list is a valid 200


@router.get("/compare", response_model=ComparisonOut)
async def compare_sessions(
    session_ids: list[uuid.UUID] = Query(..., min_length=2),  # two or more; FastAPI repeats the query key
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_recruiter),
) -> ComparisonOut:
    """Stored scores for 2+ sessions on postings this recruiter owns. Any foreign/missing id is 404."""
    unique_ids: list[uuid.UUID] = []  # preserve request order, drop duplicates
    seen: set[uuid.UUID] = set()  # first occurrence wins
    for item in session_ids:
        if item not in seen:
            seen.add(item)  # skip later repeats
            unique_ids.append(item)  # keep order
    if len(unique_ids) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="compare needs at least two distinct session_ids",
        )
    scores_out: list[ScoreOut] = []  # same order as unique_ids
    for session_id in unique_ids:
        _interview, score = await load_score_for_user(session, session_id, current_user)  # 404 if not owned
        scores_out.append(_score_out(score))  # stored row only
    return ComparisonOut(sessions=scores_out)  # recruiter-only; candidates get 403 from require_recruiter


@router.get("/{session_id}", response_model=ScoreOut)
async def read_score(
    session_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> ScoreOut:
    """Candidate: own session. Recruiter: session on an owned posting. 404 if missing or someone else's."""
    _interview, score = await load_score_for_user(session, session_id, current_user)  # shared 404 helper
    return _score_out(score)  # snake_case JSON
