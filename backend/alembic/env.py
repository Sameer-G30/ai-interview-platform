"""Alembic environment: runs migrations against our async SQLAlchemy engine/DSN."""

import asyncio  # bridges alembic's synchronous entrypoint into our async engine's connect()
import sys  # extended below so `app.*` imports resolve when alembic runs from the repo root
from logging.config import fileConfig  # wires up python logging from alembic.ini's [logger_*] sections
from pathlib import Path  # cross-platform path handling for the sys.path insert below

from sqlalchemy import pool  # NullPool avoids holding a connection pool open across a single migration run
from sqlalchemy.ext.asyncio import async_engine_from_config  # builds an AsyncEngine from an ini-style config dict

from alembic import context  # alembic's runtime context: knows which revision to run, offline vs online, etc.

# Alembic runs from the repo root (per alembic.ini's prepend_sys_path), but our packages live under backend/.
# This inserts backend/ onto sys.path so `from app.core...` imports below succeed.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import app.models  # noqa: E402,F401 - import side-effect registers every ORM model onto Base.metadata
from app.core.config import get_settings  # noqa: E402 - single source of truth for the DATABASE_URL
from app.core.db import Base  # noqa: E402 - declarative base whose .metadata drives autogenerate

# This is the Alembic Config object, which provides access to values within alembic.ini.
config = context.config

# Interpret the config file for Python logging; sets up loggers per alembic.ini's [logger_*] sections.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override whatever static sqlalchemy.url is in alembic.ini with our real, env-driven DATABASE_URL,
# so there is exactly one place (Settings, reading .env) that knows the actual DSN.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

# autogenerate diffs the live DB schema against this metadata; it stays empty of tables until
# the auth-data phase adds model classes that import into `app.models` and register on Base.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing it against a live DB connection."""
    # Pull the DSN we just injected above rather than re-reading alembic.ini directly.
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,  # render actual parameter values in emitted SQL, not bind placeholders
        dialect_opts={"paramstyle": "named"},  # matches psycopg-style named parameter rendering
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    """Sync callback: configures alembic's context against an already-open DBAPI connection."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Build an async engine, open a connection, and run migrations through it."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",       # matches the "sqlalchemy.url" key alembic.ini/env.py set above
        poolclass=pool.NullPool,    # short-lived migration run doesn't need connection pooling
    )
    # Open one connection for the whole migration run, then hand it to alembic's sync API via run_sync.
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    # Cleanly release the engine's resources once migrations finish.
    await connectable.dispose()


# Alembic calls this module at import time; dispatch to offline or online mode as usual,
# just running the online path through asyncio since our engine is async-only.
if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
