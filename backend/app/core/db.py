"""Async SQLAlchemy engine and session factory shared across the app and workers."""

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # async engine + session factory
from sqlalchemy.orm import DeclarativeBase  # SQLAlchemy 2.0-style base class all ORM models inherit from

from app.core.config import get_settings  # cached Settings object, read once and reused here

# Instantiate settings immediately so the module-level engine below can use the DSN.
settings = get_settings()

# The single async engine for the whole process; pool_pre_ping guards against stale connections.
engine = create_async_engine(settings.database_url, pool_pre_ping=True, echo=False)

# Factory used by request handlers/workers to open a new AsyncSession per unit of work.
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Common declarative base class; every ORM model in `app.models` subclasses this."""

    # No extra behavior needed yet; Alembic's autogenerate targets Base.metadata.
    pass


async def get_db_session():
    """FastAPI dependency that yields a request-scoped AsyncSession and always closes it."""
    # Open a new session bound to the shared engine for this single request/job.
    async with AsyncSessionLocal() as session:
        # Hand the session to the caller (route handler) and resume here after it's done.
        yield session
