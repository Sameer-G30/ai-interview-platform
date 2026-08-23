"""Model package: importing this module registers every ORM class on `Base.metadata`.

Import order matters only in that every module must be imported *before* SQLAlchemy's mapper
configuration runs (first query, first `Base.metadata.create_all`, or Alembic autogenerate) - the
string-based `relationship()` forward references (e.g. `Mapped["RefreshToken"]` in `user.py`) are
resolved lazily against this shared registry, not at each module's own import time.
"""

from app.models.answer import Answer  # noqa: F401 - imported for registration side-effect, not direct use here
from app.models.async_job import AsyncJob  # noqa: F401
from app.models.interview_session import InterviewSession  # noqa: F401
from app.models.job import Job  # noqa: F401
from app.models.refresh_token import RefreshToken  # noqa: F401
from app.models.resume import Resume  # noqa: F401
from app.models.score import Score  # noqa: F401
from app.models.user import User  # noqa: F401

# Explicit __all__ documents the intended public surface of this package for `from app.models import *`
# and for readers, even though Alembic/SQLAlchemy only care about the import side-effects above.
__all__ = [
    "Answer",
    "AsyncJob",
    "InterviewSession",
    "Job",
    "RefreshToken",
    "Resume",
    "Score",
    "User",
]
