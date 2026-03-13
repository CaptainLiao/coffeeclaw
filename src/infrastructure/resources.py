from dataclasses import dataclass

import redis.asyncio as redis
import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.core.config import Settings
from src.services.health import HealthStatus

logger = structlog.get_logger(__name__)


@dataclass
class AppResources:
    db_engine: AsyncEngine
    redis_client: redis.Redis
    startup_health: HealthStatus


async def init_resources(settings: Settings) -> AppResources:
    db_engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    redis_client = redis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )

    startup_health = await HealthStatus.build(db_engine=db_engine, redis_client=redis_client)
    return AppResources(
        db_engine=db_engine,
        redis_client=redis_client,
        startup_health=startup_health,
    )


async def close_resources(resources: AppResources) -> None:
    await resources.redis_client.aclose()
    await resources.db_engine.dispose()
    logger.info("Dependencies closed")
