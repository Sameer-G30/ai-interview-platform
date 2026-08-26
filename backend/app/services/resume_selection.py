"""Shared resume selection for `/matches` and `/interviews` (same 404/409 rules).

An explicit `resume_id` must belong to the caller and be `status=parsed`. Omitted `resume_id`
uses the caller's most recently created parsed resume. Missing/not-owned is 404; owned but not
yet parsed is 409; no parsed resume at all is 404. Do not collapse 409 into 404 — the frontend
empty states are different.
"""

import uuid  # optional resume_id from the query/body

from fastapi import HTTPException, status  # 404 / 409 raised for the caller to return as-is
from sqlalchemy import select  # latest-parsed-resume lookup when resume_id is omitted
from sqlalchemy.ext.asyncio import AsyncSession  # request-scoped DB session

from app.models.enums import ResumeStatus  # only PARSED resumes have skills for matching/generation
from app.models.resume import Resume  # the row this helper returns
from app.models.user import User  # authenticated caller whose ownership we check


async def resolve_parsed_resume(
    session: AsyncSession, current_user: User, resume_id: uuid.UUID | None
) -> Resume:
    """Return one owned, parsed resume, or raise 404/409 with the same details `/matches` already uses."""
    if resume_id is not None:
        resume = await session.get(Resume, resume_id)
        if resume is None or resume.user_id != current_user.id:
            # Owner-only via 404, matching GET /jobs/{id} and GET /resumes/{id} so ids are not enumerable.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resume not found")
        if resume.status != ResumeStatus.PARSED:
            # Distinct from "not found": the id is valid and owned, it just isn't ready to use yet.
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
