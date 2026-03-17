from src.orchestrator.registry import AgentRegistry
from src.orchestrator.supervisor import IntentRouter, SupervisorOrchestrator
from src.runtime.lifecycle import AgentManager
from src.runtime.repository import RuntimeRepository


def build_multi_agent_graph(
    *,
    registry: AgentRegistry,
    agent_manager: AgentManager,
    repository: RuntimeRepository,
    max_parallel_workers: int = 3,
) -> dict[str, object]:
    orchestrator = SupervisorOrchestrator(
        registry=registry,
        agent_manager=agent_manager,
        repository=repository,
        intent_router=IntentRouter(),
        max_parallel_workers=max_parallel_workers,
    )
    return orchestrator.build_supervisor_graph()


__all__ = [
    "AgentRegistry",
    "IntentRouter",
    "SupervisorOrchestrator",
    "build_multi_agent_graph",
]
