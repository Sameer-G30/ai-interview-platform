"""ARQ Redis pool helpers shared by the FastAPI process and the worker process."""

from arq import create_pool  # opens an ArqRedis connection pool from RedisSettings
from arq.connections import ArqRedis, RedisSettings  # typed pool + DSN-parsed Redis config

from app.core.config import get_settings  # cached Settings; redis_url is the single DSN source of truth


def get_redis_settings() -> RedisSettings:
    """Build ARQ RedisSettings from REDIS_URL so the API and worker always share one broker."""
    return RedisSettings.from_dsn(get_settings().redis_url)  # parses host/port/db from the DSN


async def create_arq_pool() -> ArqRedis:
    """Open a new ARQ Redis pool; callers must close it (lifespan fixture, worker shutdown)."""
    return await create_pool(get_redis_settings())  # connects using the process Settings DSN


async def close_arq_pool(redis: ArqRedis) -> None:
    """Close the pool and its underlying connections so pytest event loops do not leak sockets."""
    await redis.aclose(close_connection_pool=True)  # redis-py 5 async close; True drops the pool too
