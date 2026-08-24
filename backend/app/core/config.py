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
    frontend_origin: str = "http://localhost:5173"  # CORS allow-list; localhost/127.0.0.1 twins are expanded

    # --- Database ---
    database_url: str = (
        "postgresql+asyncpg://aiip_user:change_me_locally@localhost:5432/aiip_db"
    )  # full async SQLAlchemy DSN; overridden by DATABASE_URL in .env

    # --- Redis (ARQ broker; FastAPI enqueues, the worker process consumes) ---
    redis_url: str = "redis://localhost:6379/0"  # full redis DSN used by RedisSettings.from_dsn

    # --- Local blob storage ---
    storage_root: str = "./data/blobs"    # filesystem root for uploaded resumes/audio

    # --- Auth (JWT + Argon2id + refresh rotation) ---
    jwt_secret_key: str = "change_this_to_a_long_random_string"  # HMAC signing secret for access/refresh JWTs
    jwt_algorithm: str = "HS256"                    # PyJWT signing algorithm; symmetric since we control both ends
    access_token_expire_minutes: int = 15           # short-lived access token lifetime, minimizes stolen-token blast
    refresh_token_expire_days: int = 7              # longer-lived refresh token lifetime; rotated on every use

    # --- Rate limiting (slowapi) ---
    rate_limit_default: str = "100/minute"          # default slowapi limit string applied to auth routes


    def cors_allow_origins(self) -> list[str]:
        """Origins Starlette may echo back. `localhost` and `127.0.0.1` are different origins."""
        allowed: list[str] = []  # unique origins in the order they were discovered
        seen: set[str] = set()  # skip duplicates after expansion
        for raw in self.frontend_origin.split(","):  # FRONTEND_ORIGIN may list several
            origin = raw.strip().rstrip("/")  # "http://localhost:5174/" -> "http://localhost:5174"
            if not origin:
                continue  # ignore empty fragments from a trailing comma
            variants = [origin]  # always include the configured value as written
            if "://localhost" in origin:
                variants.append(origin.replace("://localhost", "://127.0.0.1", 1))  # Vite often prints 127.0.0.1
            elif "://127.0.0.1" in origin:
                variants.append(origin.replace("://127.0.0.1", "://localhost", 1))  # typed localhost in the address bar
            for item in variants:
                if item not in seen:
                    seen.add(item)  # first occurrence wins
                    allowed.append(item)  # keep a stable list for CORSMiddleware
        return allowed  # empty only if FRONTEND_ORIGIN was blank, which should not happen


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance so env parsing happens exactly once."""
    # Constructing Settings() triggers pydantic-settings to read env vars / .env now.
    return Settings()
