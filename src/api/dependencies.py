from fastapi import Request
from redis.asyncio.client import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from src.core.state import get_app_resources


def get_db_engine(request: Request) -> AsyncEngine:
    return get_app_resources(request.app).db_engine


def get_redis_client(request: Request) -> Redis:
    return get_app_resources(request.app).redis_client
