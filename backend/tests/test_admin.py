"""API tests for `/admin/*` user, posting, session, and score ops (Phase 15).

Does not live-generate, load MiniLM, or hit Ollama. Direct ORM inserts cover listing and 404s.
`require_admin` is 403 for candidates and recruiters without the flag; unauthenticated is 401.
"""

from __future__ import annotations  # postponed evaluation of annotations

from datetime import UTC, datetime, timedelta  # explicit created_at so newest-first is deterministic
from uuid import UUID, uuid4  # user / resume / posting ids; unknown UUID 404s

from interview_fakes import bearer, create_user_with_tokens  # register without hitting rate limits

from app.auth import service  # issue_token_pair so deactivate can assert refresh 401s
from app.core.config import get_settings  # same Settings the app uses
from app.core.db import AsyncSessionLocal  # same session factory the app uses
from app.models.enums import InterviewSessionStatus, ResumeStatus, UserRole  # insert + filter helpers
from app.models.interview_session import InterviewSession  # audit listing rows
from app.models.job import Job  # cross-recruiter posting list
from app.models.resume import Resume  # required FK on every session
from app.models.score import Score  # stored composite; GET does not recompute

settings = get_settings()  # cached; tests share the process Settings with the app


async def _create_admin(email: str, password: str = "StrongPass123") -> tuple[str, str, UUID]:
    """Register a recruiter, set `is_admin` in the DB, return (access, refresh, user_id)."""
    async with AsyncSessionLocal() as session:  # request-shaped session
        user = await service.register_user(
            session, email=email, password=password, full_name="Admin Tester", role=UserRole.RECRUITER
        )
        user.is_admin = True  # operator/ops action; RegisterRequest omits this field
        access_token, refresh_token = await service.issue_token_pair(session, user=user, settings=settings)
        await session.commit()  # persist flag + refresh row
        return access_token, refresh_token, user.id  # tokens + id


async def _insert_resume(user_id: UUID) -> UUID:
    """Insert a parsed resume so sessions can point at it without spaCy."""
    async with AsyncSessionLocal() as session:  # request-shaped session
        resume = Resume(
            user_id=user_id,  # owner
            file_path="/tmp/phase15-admin.pdf",  # never opened
            original_filename="resume.pdf",  # display only
            status=ResumeStatus.PARSED,  # sessions require a resume FK
            parsed_data={
                "skills": ["Python"],  # unused by admin listing
                "sections": {},  # unused
                "email": None,  # unused
                "phone": None,  # unused
                "extractor_used": "pymupdf",  # unused
            },
            ats_score=70.0,  # unused by the list join
        )
        session.add(resume)  # stage
        await session.commit()  # persist
        return resume.id  # UUID


async def _insert_posting(recruiter_id: UUID, title: str = "Backend engineer", *, is_active: bool = True) -> UUID:
    """Insert a posting owned by `recruiter_id` (no embedding worker)."""
    async with AsyncSessionLocal() as session:  # request-shaped session
        job = Job(
            recruiter_id=recruiter_id,  # owner
            title=title,  # echoed on admin posting + session rows
            description="Python APIs",  # unused
            required_skills="Python",  # unused by listing
            is_active=is_active,  # PATCH target
        )
        session.add(job)  # stage
        await session.commit()  # persist
        return job.id  # UUID


async def _insert_session(
    user_id: UUID,
    resume_id: UUID,
    *,
    job_id: UUID | None = None,
    status: InterviewSessionStatus = InterviewSessionStatus.SCHEDULED,
    created_at: datetime | None = None,
    composite_score: float | None = None,
    communication_score: float | None = None,
) -> UUID:
    """Insert one interview_sessions row (and an optional Score) without running the LLM worker."""
    async with AsyncSessionLocal() as session:  # request-shaped session
        interview = InterviewSession(
            user_id=user_id,  # candidate owner
            resume_id=resume_id,  # required FK
            job_id=job_id,  # null = practice; admin listing includes these
            status=status,  # audit includes scheduled / in_progress / completed / abandoned
            created_at=created_at or datetime.now(UTC),  # sort key
            completed_at=datetime.now(UTC) if status == InterviewSessionStatus.COMPLETED else None,  # score list order
        )
        session.add(interview)  # stage so interview.id exists (UUID mixin default)
        await session.flush()  # id assigned before we optionally attach Score
        if composite_score is not None:
            session.add(
                Score(
                    session_id=interview.id,  # unique per session
                    composite_score=composite_score,  # stored; GET must not recompute
                    resume_score=70.0,  # echo
                    technical_score=80.0,  # echo
                    communication_score=communication_score,  # None = omitted / "not recorded"
                    behavioral_score=None,  # omitted
                    attribution={"omitted": ["behavioral"], "signals": {}},  # unused besides presence
                )
            )
        await session.commit()  # persist
        return interview.id  # UUID


async def test_admin_unauthenticated_is_401(client):
    """GET /admin/users with no Authorization header must be 401, not 403."""
    response = await client.get("/admin/users")  # no bearer
    assert response.status_code == 401  # get_current_user before require_admin


async def test_admin_candidate_is_403(client):
    """A candidate must not list users even with a valid access token."""
    token, _ = await create_user_with_tokens("admin-cand@example.com", "StrongPass123", UserRole.CANDIDATE)
    response = await client.get("/admin/users", headers=bearer(token))  # require_admin
    assert response.status_code == 403  # not 404
    assert response.json()["detail"] == "admin privileges required"  # same string as dependencies.py


async def test_admin_recruiter_without_flag_is_403(client):
    """A recruiter with is_admin=false must not see Admin HTTP (or cross-recruiter postings)."""
    token, _ = await create_user_with_tokens("admin-rec@example.com", "StrongPass123", UserRole.RECRUITER)
    users = await client.get("/admin/users", headers=bearer(token))  # require_admin
    assert users.status_code == 403  # flag required
    postings = await client.get("/admin/postings", headers=bearer(token))  # same guard
    assert postings.status_code == 403  # not a widened GET /postings
    sessions = await client.get("/admin/sessions", headers=bearer(token))  # not GET /interviews
    assert sessions.status_code == 403  # recruiters 403 here; ranking stays on /scores/rankings
    scores = await client.get("/admin/scores", headers=bearer(token))  # stored rows only
    assert scores.status_code == 403  # not a global dump for every recruiter


async def test_admin_lists_users_and_filters_role(client):
    """Admin GET /admin/users returns accounts newest first and honors ?role=."""
    admin_token, _, admin_id = await _create_admin("admin-list@example.com")  # operator flag
    cand_token, cand_id = await create_user_with_tokens(
        "admin-list-c@example.com", "StrongPass123", UserRole.CANDIDATE
    )
    rec_token, rec_id = await create_user_with_tokens(
        "admin-list-r@example.com", "StrongPass123", UserRole.RECRUITER
    )
    del cand_token, rec_token  # listing does not need their access tokens
    listed = await client.get("/admin/users", headers=bearer(admin_token))  # collection
    assert listed.status_code == 200, listed.text  # ok
    rows = listed.json()  # list[UserOut]
    ids = [row["id"] for row in rows]  # newest created_at first
    assert str(rec_id) in ids  # recruiter present
    assert str(cand_id) in ids  # candidate present
    assert str(admin_id) in ids  # admin is also a users row
    assert "hashed_password" not in rows[0]  # UserOut never leaks the hash
    candidates = await client.get("/admin/users?role=candidate", headers=bearer(admin_token))  # filter
    assert candidates.status_code == 200, candidates.text  # ok
    cand_rows = candidates.json()  # only candidates
    assert all(row["role"] == "candidate" for row in cand_rows)  # no recruiters
    assert str(cand_id) in [row["id"] for row in cand_rows]  # the candidate we created
    assert str(admin_id) not in [row["id"] for row in cand_rows]  # admin is a recruiter


async def test_admin_unknown_user_is_404(client):
    """GET /admin/users/{id} for a never-issued UUID is 404, not 403."""
    admin_token, _, _ = await _create_admin("admin-user-404@example.com")  # operator
    missing = await client.get(f"/admin/users/{uuid4()}", headers=bearer(admin_token))  # unknown
    assert missing.status_code == 404  # not 403


async def test_admin_deactivate_blocks_me_and_refresh(client):
    """PATCH is_active=false: GET /auth/me 401s and refresh 401s without a second auth stack."""
    admin_token, _, _ = await _create_admin("admin-deact-op@example.com")  # operator
    async with AsyncSessionLocal() as session:  # mint a candidate with a live refresh token
        user = await service.register_user(
            session,
            email="admin-deact-c@example.com",
            password="StrongPass123",
            full_name="Soon Disabled",
            role=UserRole.CANDIDATE,
        )
        access_token, refresh_token = await service.issue_token_pair(session, user=user, settings=settings)
        await session.commit()  # persist
        target_id = user.id  # PATCH target
    me_before = await client.get("/auth/me", headers=bearer(access_token))  # still active
    assert me_before.status_code == 200  # baseline
    patched = await client.patch(
        f"/admin/users/{target_id}",
        json={"is_active": False},  # soft disable; no hard DELETE
        headers=bearer(admin_token),
    )
    assert patched.status_code == 200, patched.text  # ok
    assert patched.json()["is_active"] is False  # stored flag
    me_after = await client.get("/auth/me", headers=bearer(access_token))  # existing access JWT
    assert me_after.status_code == 401  # get_current_user rejects is_active=false
    refresh_after = await client.post("/auth/refresh", json={"refresh_token": refresh_token})  # existing opaque token
    assert refresh_after.status_code == 401  # rotate_refresh_token refuses inactive accounts
    listed = await client.get("/admin/users?is_active=false", headers=bearer(admin_token))  # still listable
    assert listed.status_code == 200, listed.text  # ok
    assert str(target_id) in [row["id"] for row in listed.json()]  # soft-disabled rows stay on the ops list


async def test_admin_cannot_deactivate_self(client):
    """An admin PATCHing their own is_active=false is 409 so they cannot lock themselves out."""
    admin_token, _, admin_id = await _create_admin("admin-self@example.com")  # operator
    response = await client.patch(
        f"/admin/users/{admin_id}",
        json={"is_active": False},  # would 401 every subsequent /admin call
        headers=bearer(admin_token),
    )
    assert response.status_code == 409  # conflict, not 200
    still = await client.get("/auth/me", headers=bearer(admin_token))  # still active
    assert still.status_code == 200  # flag unchanged
    assert still.json()["is_active"] is True  # not deactivated


async def test_admin_is_admin_only_on_recruiters(client):
    """PATCH is_admin=true on a candidate is 422; on a recruiter it sticks. Register still cannot set it."""
    admin_token, _, _ = await _create_admin("admin-flag-op@example.com")  # operator
    _, cand_id = await create_user_with_tokens("admin-flag-c@example.com", "StrongPass123", UserRole.CANDIDATE)
    _, rec_id = await create_user_with_tokens("admin-flag-r@example.com", "StrongPass123", UserRole.RECRUITER)
    bad = await client.patch(
        f"/admin/users/{cand_id}",
        json={"is_admin": True},  # candidates never get the flag
        headers=bearer(admin_token),
    )
    assert bad.status_code == 422  # not 200
    granted = await client.patch(
        f"/admin/users/{rec_id}",
        json={"is_admin": True},  # recruiters only
        headers=bearer(admin_token),
    )
    assert granted.status_code == 200, granted.text  # ok
    assert granted.json()["is_admin"] is True  # stored
    assert granted.json()["role"] == "recruiter"  # still not UserRole.ADMIN
    empty = await client.patch(
        f"/admin/users/{rec_id}",
        json={},  # neither field
        headers=bearer(admin_token),
    )
    assert empty.status_code == 422  # provide is_active and/or is_admin


async def test_admin_lists_all_recruiters_postings_and_patch_is_active(client):
    """GET /admin/postings sees every recruiter's jobs; PATCH is_active; unknown id is 404."""
    admin_token, _, _ = await _create_admin("admin-post-op@example.com")  # operator
    rec_token, rec_id = await create_user_with_tokens(
        "admin-post-r@example.com", "StrongPass123", UserRole.RECRUITER
    )
    other_token, other_id = await create_user_with_tokens(
        "admin-post-r2@example.com", "StrongPass123", UserRole.RECRUITER
    )
    posting_a = await _insert_posting(rec_id, title="Staff Python")  # other recruiter's job
    posting_b = await _insert_posting(other_id, title="Platform")  # second owner
    del rec_token, other_token  # admin list does not use their tokens
    listed = await client.get("/admin/postings", headers=bearer(admin_token))  # cross-recruiter
    assert listed.status_code == 200, listed.text  # ok
    titles = {row["title"]: row for row in listed.json()}  # by title
    assert "Staff Python" in titles  # first owner's posting
    assert "Platform" in titles  # second owner's posting
    assert titles["Staff Python"]["recruiter_id"] == str(rec_id)  # owner id
    assert titles["Staff Python"]["recruiter_email"] == "admin-post-r@example.com"  # owner email
    assert titles["Staff Python"]["has_embedding"] is False  # no worker ran
    patched = await client.patch(
        f"/admin/postings/{posting_a}",
        json={"is_active": False},  # prefer is_active over hard DELETE
        headers=bearer(admin_token),
    )
    assert patched.status_code == 200, patched.text  # ok
    assert patched.json()["is_active"] is False  # stored
    assert patched.json()["id"] == str(posting_a)  # same posting
    fetched = await client.get(f"/admin/postings/{posting_b}", headers=bearer(admin_token))  # other owner's id
    assert fetched.status_code == 200, fetched.text  # admin can read any posting
    assert fetched.json()["title"] == "Platform"  # second posting
    missing = await client.get(f"/admin/postings/{uuid4()}", headers=bearer(admin_token))  # unknown
    assert missing.status_code == 404  # not 403


async def test_admin_sessions_include_practice_and_unknown_is_404(client):
    """Admin session listing includes practice; GET /interviews stays candidate-own-only."""
    admin_token, _, _ = await _create_admin("admin-sess-op@example.com")  # operator
    cand_token, cand_id = await create_user_with_tokens(
        "admin-sess-c@example.com", "StrongPass123", UserRole.CANDIDATE
    )
    rec_token, rec_id = await create_user_with_tokens(
        "admin-sess-r@example.com", "StrongPass123", UserRole.RECRUITER
    )
    resume_id = await _insert_resume(cand_id)  # FK
    posting_id = await _insert_posting(rec_id, title="Staff Python")  # posting_title echo
    older = datetime.now(UTC) - timedelta(seconds=30)  # first insert, should sort second
    newer = datetime.now(UTC) - timedelta(seconds=5)  # second insert, should sort first
    practice_id = await _insert_session(
        cand_id,
        resume_id,
        status=InterviewSessionStatus.ABANDONED,  # no Score
        created_at=older,  # older
    )
    posting_session_id = await _insert_session(
        cand_id,
        resume_id,
        job_id=posting_id,  # posting-targeted
        status=InterviewSessionStatus.COMPLETED,  # scored
        created_at=newer,  # newer
        composite_score=88.5,  # stored Score join
        communication_score=None,  # omitted; listing only exposes composite
    )
    listed = await client.get("/admin/sessions", headers=bearer(admin_token))  # ops dump
    assert listed.status_code == 200, listed.text  # ok
    rows = listed.json()  # list[AdminSessionListItemOut]
    assert [row["id"] for row in rows] == [str(posting_session_id), str(practice_id)]  # newest first
    assert rows[0]["candidate_email"] == "admin-sess-c@example.com"  # identifiable
    assert rows[0]["job_id"] == str(posting_id)  # posting session
    assert rows[0]["posting_title"] == "Staff Python"  # Job.title
    assert rows[0]["composite_score"] == 88.5  # stored, not recomputed
    assert rows[1]["job_id"] is None  # practice belongs on admin audit
    assert rows[1]["posting_title"] is None  # no posting
    assert rows[1]["composite_score"] is None  # abandoned has no Score
    own = await client.get("/interviews", headers=bearer(cand_token))  # candidate history still works
    assert own.status_code == 200  # own rows
    rec_list = await client.get("/interviews", headers=bearer(rec_token))  # recruiter
    assert rec_list.status_code == 403  # GET /interviews is not a global dump
    missing = await client.get(f"/admin/sessions/{uuid4()}", headers=bearer(admin_token))  # unknown
    assert missing.status_code == 404  # not 403
    one = await client.get(f"/admin/sessions/{practice_id}", headers=bearer(admin_token))  # practice detail
    assert one.status_code == 200, one.text  # ok
    assert one.json()["id"] == str(practice_id)  # same UUID
    filtered = await client.get("/admin/sessions?status=completed", headers=bearer(admin_token))  # query alias
    assert filtered.status_code == 200, filtered.text  # ok
    assert [row["id"] for row in filtered.json()] == [str(posting_session_id)]  # abandoned dropped


async def test_admin_scores_include_practice_and_unknown_is_404(client):
    """Admin score listing reads stored rows including practice; omitted communication stays null."""
    admin_token, _, _ = await _create_admin("admin-score-op@example.com")  # operator
    _, cand_id = await create_user_with_tokens("admin-score-c@example.com", "StrongPass123", UserRole.CANDIDATE)
    resume_id = await _insert_resume(cand_id)  # FK
    practice_id = await _insert_session(
        cand_id,
        resume_id,
        status=InterviewSessionStatus.COMPLETED,  # scored practice
        composite_score=73.0,  # stored
        communication_score=None,  # text-only
    )
    open_id = await _insert_session(
        cand_id,
        resume_id,
        status=InterviewSessionStatus.IN_PROGRESS,  # no Score
    )
    listed = await client.get("/admin/scores", headers=bearer(admin_token))  # stored only
    assert listed.status_code == 200, listed.text  # ok
    rows = listed.json()  # list[AdminScoreListItemOut]
    assert [row["session_id"] for row in rows] == [str(practice_id)]  # in_progress omitted
    assert rows[0]["job_id"] is None  # practice is ops-visible
    assert rows[0]["composite_score"] == 73.0  # stored
    assert rows[0]["communication_score"] is None  # omitted, not a fake 0
    assert rows[0]["candidate_email"] == "admin-score-c@example.com"  # identifiable
    detail = await client.get(f"/admin/scores/{practice_id}", headers=bearer(admin_token))  # one row
    assert detail.status_code == 200, detail.text  # ok
    assert detail.json()["composite_score"] == 73.0  # same stored value
    missing = await client.get(f"/admin/scores/{uuid4()}", headers=bearer(admin_token))  # unknown
    assert missing.status_code == 404  # not 403
    open_score = await client.get(f"/admin/scores/{open_id}", headers=bearer(admin_token))  # in_progress
    assert open_score.status_code == 404  # no composite yet
    empty_status = await client.get("/admin/sessions?status=scheduled", headers=bearer(admin_token))  # no scheduled
    assert empty_status.status_code == 200  # empty is success
    assert empty_status.json() == []  # dashboard empty state


async def test_admin_empty_patch_user_unknown_is_404(client):
    """PATCH /admin/users/{unknown} is 404 even with a valid body."""
    admin_token, _, _ = await _create_admin("admin-patch-404@example.com")  # operator
    response = await client.patch(
        f"/admin/users/{uuid4()}",
        json={"is_active": False},  # would deactivate if the id existed
        headers=bearer(admin_token),
    )
    assert response.status_code == 404  # not 403
