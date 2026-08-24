"""`/matches` endpoint: candidate-only ranked postings for one parsed resume.

No "list my resumes" endpoint exists yet, so this router resolves which resume to match against
itself: an explicit `?resume_id=` (must belong to the caller and be `status=parsed`), or - when
omitted - the caller's own most recently created `parsed` resume. Ranking uses `SbertBackend` over
precomputed pgvector embeddings; the TF-IDF baseline lives in `ml/matching` behind the same
interface but is not exposed here (covered by its own unit test instead, per the plan).
"""

import uuid  # optional ?resume_id= query param

from fastapi import APIRouter, Depends, HTTPException, Query, status  # routing / DI / errors
from ml.matching import PostingForMatch, SbertBackend  # production ranking backend + its input shape
from ml.matching.similarity import skill_gap  # case-insensitive matched/missing skill diff
from ml.resume.skills import extract_skills  # ESCO PhraseMatcher, reused for posting required_skills text
from sqlalchemy import select  # active+embedded postings query, latest-parsed-resume lookup
from sqlalchemy.ext.asyncio import AsyncSession  # request-scoped DB session

from app.auth.dependencies import require_candidate  # only candidates match against postings
from app.core.db import get_db_session  # yields the request-scoped AsyncSession
from app.models.enums import ResumeStatus  # only a PARSED resume has skills/embedding to match with
from app.models.job import Job  # postings ranked against the resume
from app.models.resume import Resume  # the resume this router resolves and reads
from app.models.user import User  # type of the authenticated candidate
from app.schemas.matches import MatchListOut, MatchOut  # response contracts

router = APIRouter(prefix="/matches", tags=["matches"])  # single GET route lives under /matches


async def _resolve_resume(
    session: AsyncSession, current_user: User, resume_id: uuid.UUID | None
) -> Resume:
    """Return the resume to match against, or raise 404/409 per the rules documented on the router."""
    if resume_id is not None:
        resume = await session.get(Resume, resume_id)
        if resume is None or resume.user_id != current_user.id:
            # Owner-only via 404, matching every other owner-scoped lookup in this codebase (jobs, resumes).
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resume not found")
        if resume.status != ResumeStatus.PARSED:
            # Distinct from "not found": the id is valid and owned, it just isn't ready to match with yet.
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="resume has not finished parsing yet")
        return resume

    result = await session.execute(
        select(Resume)
        .where(Resume.user_id == current_user.id, Resume.status == ResumeStatus.PARSED)
        .order_by(Resume.created_at.desc())
        .limit(1)
    )
    resume = result.scalars().first()
    if resume is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no parsed resume found")
    return resume


@router.get("", response_model=MatchListOut)
async def list_matches(
    resume_id: uuid.UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(require_candidate),
) -> MatchListOut:
    """Rank every active, embedded posting against one of the caller's parsed resumes."""
    resume = await _resolve_resume(session, current_user, resume_id)
    resume_skills: list[str] = (resume.parsed_data or {}).get("skills", [])  # ESCO preferred labels

    result = await session.execute(
        select(Job).where(Job.is_active.is_(True), Job.embedding.is_not(None)).order_by(Job.created_at.desc())
    )
    postings = list(result.scalars().all())

    match_inputs = [
        PostingForMatch(
            posting_id=str(posting.id),
            text=f"{posting.title}\n\n{posting.description}",
            embedding=list(posting.embedding) if posting.embedding is not None else None,
        )
        for posting in postings
    ]
    scores = SbertBackend().rank(
        resume_text="",  # SbertBackend ignores raw text; ranking is purely embedding-based
        resume_embedding=list(resume.embedding) if resume.embedding is not None else None,
        postings=match_inputs,
    )

    ranked: list[MatchOut] = []
    for posting, score in zip(postings, scores, strict=True):
        required_skills = extract_skills(posting.required_skills or "")
        matched, missing = skill_gap(resume_skills, required_skills)
        ranked.append(
            MatchOut(
                posting_id=posting.id,
                title=posting.title,
                score=score,
                matched_skills=matched,
                missing_skills=missing,
            )
        )
    ranked.sort(key=lambda match: match.score, reverse=True)  # best match first

    return MatchListOut(resume_id=resume.id, matches=ranked)
