from dataclasses import dataclass

import redis.asyncio as redis
import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.core.config import Settings
from src.orchestrator.registry import AgentRegistry
from src.orchestrator.supervisor import SupervisorOrchestrator
from src.runtime.adapters import (
    InMemoryShortTermMemoryAdapter,
    RedisShortTermMemoryAdapter,
    ShortTermMemoryAdapter,
)
from src.runtime.checkpoint import RuntimeCheckpointer
from src.runtime.repository import RuntimeRepository, SqlRuntimeRepository
from src.services.health import HealthStatus
from src.tools import ToolCaller
from src.tools.registry import ToolRegistry
from src.tools.skills import SkillManager

logger = structlog.get_logger(__name__)


@dataclass
class AppResources:
    db_engine: AsyncEngine | None
    redis_client: redis.Redis | None
    runtime_repository: RuntimeRepository
    memory_adapter: ShortTermMemoryAdapter
    runtime_checkpointer: RuntimeCheckpointer
    tool_registry: ToolRegistry
    tool_caller: ToolCaller
    skill_manager: SkillManager
    orchestrator_registry: AgentRegistry
    orchestrator_manager: SupervisorOrchestrator
    startup_health: HealthStatus


async def init_resources(settings: Settings) -> AppResources:
    needs_db = (
        settings.runtime_repository_backend == "postgres"
        or settings.checkpoint_backend == "postgres"
    )
    db_engine: AsyncEngine | None = None
    if needs_db:
        db_engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)

    needs_redis = settings.shortterm_memory_backend == "redis"
    redis_client: redis.Redis | None = None
    if needs_redis:
        redis_client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )

    runtime_repository: RuntimeRepository
    if settings.runtime_repository_backend == "postgres":
        if db_engine is None:
            raise RuntimeError("runtime_repository_backend=postgres requires postgres_dsn.")
        runtime_repository = SqlRuntimeRepository(db_engine)
    else:
        from src.runtime.repository import InMemoryRuntimeRepository

        runtime_repository = InMemoryRuntimeRepository()

    if settings.shortterm_memory_backend == "redis":
        if redis_client is None:
            raise RuntimeError("shortterm_memory_backend=redis requires redis_url.")
        memory_adapter: ShortTermMemoryAdapter = RedisShortTermMemoryAdapter(redis_client)
    else:
        memory_adapter = InMemoryShortTermMemoryAdapter()

    runtime_checkpointer = RuntimeCheckpointer(
        postgres_dsn=settings.postgres_dsn if settings.checkpoint_backend == "postgres" else None,
        in_memory=settings.checkpoint_backend == "memory",
    )
    await runtime_checkpointer.initialize()

    tool_registry = ToolRegistry.instance()
    tool_registry.load_from_dir("configs/tools")
    skill_manager = SkillManager()
    skill_manager.load_from_dir("configs/skills")
    tool_caller = ToolCaller(registry=tool_registry)
    orchestrator_registry = AgentRegistry.from_file("configs/agents/agent-registry.yaml")
    from src.runtime.lifecycle import AgentManager

    orchestrator_agent_manager = AgentManager.from_resources(
        repository=runtime_repository,
        memory_adapter=memory_adapter,
        checkpointer=runtime_checkpointer,
        tool_caller=tool_caller,
        skill_manager=skill_manager,
        runtime_settings=settings,
    )
    orchestrator_manager = SupervisorOrchestrator(
        registry=orchestrator_registry,
        agent_manager=orchestrator_agent_manager,
        repository=runtime_repository,
    )

    startup_health = await HealthStatus.build(db_engine=db_engine, redis_client=redis_client)
    return AppResources(
        db_engine=db_engine,
        redis_client=redis_client,
        runtime_repository=runtime_repository,
        memory_adapter=memory_adapter,
        runtime_checkpointer=runtime_checkpointer,
        tool_registry=tool_registry,
        tool_caller=tool_caller,
        skill_manager=skill_manager,
        orchestrator_registry=orchestrator_registry,
        orchestrator_manager=orchestrator_manager,
        startup_health=startup_health,
    )


async def close_resources(resources: AppResources) -> None:
    await resources.runtime_checkpointer.close()
    if resources.redis_client is not None:
        await resources.redis_client.aclose()
    if resources.db_engine is not None:
        await resources.db_engine.dispose()
    logger.info("Dependencies closed")
