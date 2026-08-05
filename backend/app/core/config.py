"""Typed application settings loaded from environment variables / .env file."""

from functools import lru_cache  # memoizes get_settings() so env parsing happens once per process

from pydantic_settings import BaseSettings, SettingsConfigDict  # typed settings model backed by env vars


class Settings(BaseSettings):
    """All runtime configuration for the FastAPI app, sourced from `.env`."""

    # Tells pydantic-settings where to look for a dotenv file and to ignore unknown keys gracefully.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App / environment ---
    app_env: str = "development"          # development | test | production; toggles debug behavior
    app_name: str = "AI Interview Intelligence Platform"  # human-readable name used in docs/logs
    api_host: str = "0.0.0.0"             # interface uvicorn binds to
    api_port: int = 8000                  # port uvicorn listens on
    frontend_origin: str = "http://localhost:5173"  # allowed CORS origin for the Vite dev server

    # --- Database ---
    database_url: str = (
        "postgresql+asyncpg://aiip_user:change_me_locally@localhost:5432/aiip_db"
    )  # full async SQLAlchemy DSN; overridden by DATABASE_URL in .env

    # --- Redis (used by ARQ starting in the queue-infrastructure phase) ---
    redis_url: str = "redis://localhost:6379/0"  # full redis DSN

    # --- Local blob storage ---
    storage_root: str = "./data/blobs"    # filesystem root for uploaded resumes/audio


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance so env parsing happens exactly once."""
    # Constructing Settings() triggers pydantic-settings to read env vars / .env now.
    return Settings()
