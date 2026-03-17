from dataclasses import dataclass

import redis.asyncio as redis
import structlog
from sqlalchemy.ext.asyncio import AsyncEngine

from src.core.config import Settings
from src.infrastructure.runtime_backends import (
    RuntimeBackendResources,
    close_runtime_backends,
    init_runtime_backends,
)
from src.orchestrator.registry import AgentRegistry
from src.orchestrator.supervisor import SupervisorOrchestrator
from src.runtime.adapters import ShortTermMemoryAdapter
from src.runtime.checkpoint import RuntimeCheckpointer
from src.runtime.repository import RuntimeRepository
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
    runtime_backends = await init_runtime_backends(settings)
    try:
        tool_registry = ToolRegistry()
        tool_registry.load_from_dir("configs/tools")
        skill_manager = SkillManager()
        skill_manager.load_from_dir("configs/skills")
        tool_caller = ToolCaller(registry=tool_registry)
        orchestrator_registry = AgentRegistry.from_file("configs/agents/agent-registry.yaml")
        from src.runtime.lifecycle import AgentManager

        orchestrator_agent_manager = AgentManager.from_resources(
            repository=runtime_backends.runtime_repository,
            memory_adapter=runtime_backends.memory_adapter,
            checkpointer=runtime_backends.runtime_checkpointer,
            tool_caller=tool_caller,
            skill_manager=skill_manager,
            runtime_settings=settings,
        )
        orchestrator_manager = SupervisorOrchestrator(
            registry=orchestrator_registry,
            agent_manager=orchestrator_agent_manager,
            repository=runtime_backends.runtime_repository,
        )
        startup_health = await HealthStatus.build(
            db_engine=runtime_backends.db_engine,
            redis_client=runtime_backends.redis_client,
        )
        return AppResources(
            db_engine=runtime_backends.db_engine,
            redis_client=runtime_backends.redis_client,
            runtime_repository=runtime_backends.runtime_repository,
            memory_adapter=runtime_backends.memory_adapter,
            runtime_checkpointer=runtime_backends.runtime_checkpointer,
            tool_registry=tool_registry,
            tool_caller=tool_caller,
            skill_manager=skill_manager,
            orchestrator_registry=orchestrator_registry,
            orchestrator_manager=orchestrator_manager,
            startup_health=startup_health,
        )
    except Exception:
        await close_runtime_backends(runtime_backends)
        raise


async def close_resources(resources: AppResources) -> None:
    await close_runtime_backends(
        RuntimeBackendResources(
            db_engine=resources.db_engine,
            redis_client=resources.redis_client,
            runtime_repository=resources.runtime_repository,
            memory_adapter=resources.memory_adapter,
            runtime_checkpointer=resources.runtime_checkpointer,
        )
    )
    logger.info("Dependencies closed")
