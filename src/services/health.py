from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, cast

import structlog
from redis.asyncio.client import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = structlog.get_logger(__name__)


async def check_db_connection(engine: AsyncEngine | None) -> bool:
    if engine is None:
        return False

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("Database health check failed", exc_info=True)
        return False


async def check_redis_connection(client: Redis | None) -> bool:
    if client is None:
        return False

    try:
        await cast(Awaitable[Any], client.ping())
        return True
    except Exception:
        logger.warning("Redis health check failed", exc_info=True)
        return False


@dataclass(frozen=True)
class HealthStatus:
    status: str
    db: bool
    redis: bool

    @classmethod
    async def build(
        cls,
        db_engine: AsyncEngine | None,
        redis_client: Redis | None,
    ) -> "HealthStatus":
        db_healthy = await check_db_connection(db_engine)
        redis_healthy = await check_redis_connection(redis_client)
        return cls(
            status="ok" if db_healthy and redis_healthy else "degraded",
            db=db_healthy,
            redis=redis_healthy,
        )
