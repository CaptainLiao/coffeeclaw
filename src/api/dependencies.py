from fastapi import Request
from redis.asyncio.client import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from src.core.state import (
    get_agent_manager_state,
    get_app_resources,
    get_orchestrator_manager_state,
)
from src.orchestrator.supervisor import SupervisorOrchestrator
from src.runtime.lifecycle import AgentManager


def get_db_engine(request: Request) -> AsyncEngine | None:
    return get_app_resources(request.app).db_engine


def get_redis_client(request: Request) -> Redis | None:
    return get_app_resources(request.app).redis_client


def get_agent_manager(request: Request) -> AgentManager:
    manager = get_agent_manager_state(request.app)
    if manager is not None:
        return manager

    resources = get_app_resources(request.app)
    manager = AgentManager.from_resources(
        repository=resources.runtime_repository,
        memory_adapter=resources.memory_adapter,
        checkpointer=resources.runtime_checkpointer,
        tool_caller=resources.tool_caller,
        skill_manager=resources.skill_manager,
    )
    request.app.state.agent_manager = manager
    return manager


def get_orchestrator_manager(request: Request) -> SupervisorOrchestrator:
    manager = get_orchestrator_manager_state(request.app)
    if manager is not None:
        return manager

    resources = get_app_resources(request.app)
    manager = resources.orchestrator_manager
    request.app.state.orchestrator_manager = manager
    return manager
