from fastapi import Request
from redis.asyncio.client import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from src.core.state import get_agent_manager_state, get_app_resources
from src.runtime.lifecycle import AgentManager


def get_db_engine(request: Request) -> AsyncEngine:
    return get_app_resources(request.app).db_engine


def get_redis_client(request: Request) -> Redis:
    return get_app_resources(request.app).redis_client


def get_agent_manager(request: Request) -> AgentManager:
    manager = get_agent_manager_state(request.app)
    if manager is not None:
        return manager

    resources = get_app_resources(request.app)
    manager = AgentManager.from_resources(
        db_engine=resources.db_engine,
        redis_client=resources.redis_client,
        checkpointer=resources.runtime_checkpointer,
    )
    request.app.state.agent_manager = manager
    return manager
