from typing import Annotated

from fastapi import APIRouter, Depends
from redis.asyncio.client import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from src.api.dependencies import get_db_engine, get_redis_client
from src.api.schemas import HealthResponse
from src.services.health import HealthStatus

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health_check(
    db_engine: Annotated[AsyncEngine, Depends(get_db_engine)],
    redis_client: Annotated[Redis, Depends(get_redis_client)],
) -> HealthResponse:
    health = await HealthStatus.build(db_engine=db_engine, redis_client=redis_client)
    return HealthResponse(**health.__dict__)
