"""Create demo candidate, recruiter, and admin accounts without wiping Postgres.

Safe to run more than once. Existing rows are left in place, including any phase15-* accounts
already in this database. The admin flag is applied with SQL after insert. POST /auth/register
cannot set it. Passwords come from SEED_DEMO_PASSWORD or the placeholder in .env.example.
Nothing in this file is a production secret.

Run from the repo root:

    uv run python scripts/seed_demo.py
"""

import asyncio  # one event loop for the async SQLAlchemy session
import os  # SEED_DEMO_PASSWORD, when the operator exported it
import sys  # non-zero exit when the admin email cannot receive the flag

from dotenv import load_dotenv  # .env is not copied into os.environ by pydantic-settings
from sqlalchemy import select, text  # lookup by email, and the operator UPDATE

from app.auth import service  # register_user hashes with Argon2id; this script does not reimplement that
from app.core.db import AsyncSessionLocal  # same engine the API uses, pointed at DATABASE_URL
from app.models.enums import UserRole  # candidate or recruiter; there is no ADMIN member
from app.models.job import Job  # one demo posting, embedding left null on purpose
from app.models.user import User  # read-back after the UPDATE

# Fixed demo addresses. They do not overlap the phase15 walkthrough accounts.
DEMO_CANDIDATE_EMAIL = "demo-candidate@example.com"  # candidate persona
DEMO_RECRUITER_EMAIL = "demo-recruiter@example.com"  # recruiter persona, is_admin stays false
DEMO_ADMIN_EMAIL = "demo-admin@example.com"  # recruiter persona, then the SQL flag
# Placeholder only. Override with SEED_DEMO_PASSWORD in .env. A real password must not be committed.
DEFAULT_PASSWORD = "change_me_locally"  # same placeholder style as POSTGRES_PASSWORD in .env.example
# Title used to find the demo posting again. A second run does not insert a duplicate.
DEMO_POSTING_TITLE = "Demo platform engineer"  # shown on the recruiter Jobs page
# The Postgres enum label is the Python member name. The JSON API still says "recruiter".
# `role = 'recruiter'` is an invalid enum value and errors. This statement is the one that works.
GRANT_ADMIN_SQL = "UPDATE users SET is_admin = true WHERE email = :email AND role = 'RECRUITER'"  # first-admin flag


async def _ensure_user(session, *, email: str, password: str, full_name: str, role: UserRole) -> tuple[User, str]:
    """Return the user for `email`, creating them only when missing. Never changes an existing password."""
    existing = await session.scalar(select(User).where(User.email == email))  # one row or none
    if existing is not None:
        return existing, "already present"  # do not reset password, role, or is_active
    created = await service.register_user(
        session, email=email, password=password, full_name=full_name, role=role
    )  # is_admin is forced false inside register_user
    return created, "created"  # flushed, not committed; the caller commits once


async def _ensure_posting(session, recruiter: User) -> str:
    """Insert one active posting with a null embedding when this recruiter does not already have it."""
    existing = await session.scalar(
        select(Job).where(Job.recruiter_id == recruiter.id, Job.title == DEMO_POSTING_TITLE)
    )  # idempotent lookup
    if existing is not None:
        return "already present"  # leave has_embedding however the row already is; do not null it out
    session.add(
        Job(
            recruiter_id=recruiter.id,  # demo-recruiter, not the admin
            title=DEMO_POSTING_TITLE,  # stable title for the lookup above
            description="Demo posting created by scripts/seed_demo.py. It is not embedded.",  # no MiniLM call
            required_skills="Python, Docker",  # free text; the matcher will not see this until embedding exists
            is_active=True,  # visible to the owner; /matches still skips it while embedding is null
        )
    )  # embedding column stays NULL because this script does not enqueue posting_embed
    return "created"  # flushed with the users on the caller's commit


async def _seed() -> int:
    """Insert the three demo users, grant the admin flag with SQL, and add one unembedded posting."""
    load_dotenv()  # pick up SEED_DEMO_PASSWORD from .env without overriding a real exported value
    password = os.environ.get("SEED_DEMO_PASSWORD", DEFAULT_PASSWORD)  # never hardcoded as a live secret
    if len(password) < 8:
        print("SEED_DEMO_PASSWORD must be at least 8 characters.", file=sys.stderr)  # register_user would reject it too
        return 1  # do not open a transaction
    async with AsyncSessionLocal() as session:  # one transaction for the whole seed
        candidate, candidate_state = await _ensure_user(
            session,
            email=DEMO_CANDIDATE_EMAIL,
            password=password,
            full_name="Demo Candidate",
            role=UserRole.CANDIDATE,
        )  # candidate cannot be admin
        recruiter, recruiter_state = await _ensure_user(
            session,
            email=DEMO_RECRUITER_EMAIL,
            password=password,
            full_name="Demo Recruiter",
            role=UserRole.RECRUITER,
        )  # is_admin stays false for this one
        admin, admin_state = await _ensure_user(
            session,
            email=DEMO_ADMIN_EMAIL,
            password=password,
            full_name="Demo Admin",
            role=UserRole.RECRUITER,
        )  # still is_admin false until the UPDATE below
        if admin.role != UserRole.RECRUITER:
            print(
                f"{DEMO_ADMIN_EMAIL} already exists with role {admin.role.value!r}. "
                "Refusing to change that role or to set is_admin. No rows were committed.",
                file=sys.stderr,
            )  # a candidate with this email must not be promoted by a re-run
            return 1  # the context manager rolls the new inserts back
        await session.execute(text(GRANT_ADMIN_SQL), {"email": DEMO_ADMIN_EMAIL})  # operator SQL, scoped to one email
        await session.refresh(admin)  # the UPDATE bypassed the identity map
        if admin.is_admin is not True:
            print(f"{DEMO_ADMIN_EMAIL} is still not admin. Nothing was committed.", file=sys.stderr)
            return 1  # roll back; the enum label or the email did not match
        posting_state = await _ensure_posting(session, recruiter)  # null embedding; no worker, no MiniLM
        # Copy ids before commit. expire_on_commit would detach them once the session closes.
        candidate_id = str(candidate.id)  # not secret
        recruiter_id = str(recruiter.id)  # posting owner
        admin_id = str(admin.id)  # the recruiter the UPDATE touched
        await session.commit()  # first successful point; earlier returns committed nothing
    _print_summary(
        password=password,  # printed only when it is the documented placeholder
        candidate_state=candidate_state,  # created or already present
        recruiter_state=recruiter_state,  # created or already present
        admin_state=admin_state,  # created or already present; the flag was set either way
        posting_state=posting_state,  # created or already present
        candidate_id=candidate_id,  # captured before commit
        recruiter_id=recruiter_id,  # captured before commit
        admin_id=admin_id,  # captured before commit
    )
    return 0  # success


def _print_summary(
    *,
    password: str,
    candidate_state: str,
    recruiter_state: str,
    admin_state: str,
    posting_state: str,
    candidate_id: str,
    recruiter_id: str,
    admin_id: str,
) -> None:
    """Tell the operator what happened. Do not echo a non-default password."""
    print("Seed finished. No tables were truncated.")  # this script never deletes
    print(f"  candidate {DEMO_CANDIDATE_EMAIL} ({candidate_id}): {candidate_state}")  # persona 1
    print(f"  recruiter {DEMO_RECRUITER_EMAIL} ({recruiter_id}): {recruiter_state}, is_admin left false")  # persona 2
    print(f"  admin     {DEMO_ADMIN_EMAIL} ({admin_id}): {admin_state}, is_admin set with SQL")  # persona 3
    print(f"  posting   {DEMO_POSTING_TITLE!r} for {DEMO_RECRUITER_EMAIL}: {posting_state}")  # may lack an embedding
    print("  The posting is not embedded. Do not assume has_embedding is true until a worker runs posting_embed.")
    print("  This script does not enqueue that job and does not call MiniLM.")  # safe if a worker is already up
    if password == DEFAULT_PASSWORD:
        print(f"  Password: {DEFAULT_PASSWORD} (placeholder from .env.example)")  # only the known default
    else:
        print("  Password: SEED_DEMO_PASSWORD from the environment (not printed).")  # override stays out of the log
    print("  Existing passwords were not reset. phase15-* accounts were not modified.")  # re-run contract
    print("First admin flag is SQL, not register. JSON role is recruiter; the enum label is RECRUITER:")
    print(f"  UPDATE users SET is_admin = true WHERE email = '{DEMO_ADMIN_EMAIL}' AND role = 'RECRUITER';")
    print("  role = 'recruiter' is invalid for this database and errors. Use the uppercase label.")  # the footgun


def main() -> None:
    """CLI entry. Exit status is the seed result."""
    sys.exit(asyncio.run(_seed()))  # 0 on success, 1 when the admin email cannot take the flag


if __name__ == "__main__":
    main()  # `uv run python scripts/seed_demo.py`
