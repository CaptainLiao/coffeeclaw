from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import api_router
from src.api.system import router as system_router
from src.core.config import settings
from src.core.state import get_agent_manager_state
from src.infrastructure.resources import close_resources, init_resources
from src.observability.http import (
    register_exception_handlers,
    register_request_context_middleware,
)
from src.observability.logging import setup_logging
from src.runtime.lifecycle import AgentManager

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging(settings.log_level)
    logger.info("Application starting up", env=settings.app_env)

    resources = await init_resources(settings)
    app.state.resources = resources
    recovered_tasks = 0
    if all(
        hasattr(resources, attr)
        for attr in (
            "runtime_repository",
            "memory_adapter",
            "runtime_checkpointer",
            "tool_caller",
            "skill_manager",
        )
    ):
        agent_manager = AgentManager.from_resources(
            repository=resources.runtime_repository,
            memory_adapter=resources.memory_adapter,
            checkpointer=resources.runtime_checkpointer,
            tool_caller=resources.tool_caller,
            skill_manager=resources.skill_manager,
            runtime_settings=settings,
        )
        app.state.agent_manager = agent_manager
        recovered_tasks = await agent_manager.recover_interrupted_tasks()
    logger.info(
        "Dependencies initialized",
        db=resources.startup_health.db,
        redis=resources.startup_health.redis,
        recovered_tasks=recovered_tasks,
    )

    yield

    logger.info("Application shutting down")
    manager = get_agent_manager_state(app)
    if manager is not None:
        await manager.shutdown()
    await close_resources(resources)


def _configure_middleware(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_request_context_middleware(app)


def create_app() -> FastAPI:
    app = FastAPI(
        title="CoffeeClaw",
        version="0.1.0",
        description="Enterprise AI Agent Development Platform",
        lifespan=lifespan,
    )

    _configure_middleware(app)
    register_exception_handlers(app)
    app.include_router(system_router)
    app.include_router(api_router, prefix="/api/v1")
    return app
