import asyncio
from types import SimpleNamespace
from typing import Any, cast

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from src.core import app as app_module
from src.core.app import create_app
from src.orchestrator.registry import AgentRegistry
from src.orchestrator.supervisor import IntentRouter, SupervisorOrchestrator
from src.runtime.checkpoint import RuntimeCheckpointer
from src.runtime.lifecycle import AgentManager
from src.runtime.repository import InMemoryRuntimeRepository


def _build_orchestrator() -> tuple[SupervisorOrchestrator, InMemoryRuntimeRepository]:
    repository = InMemoryRuntimeRepository()
    manager = AgentManager.for_tests(repository=repository)
    registry = AgentRegistry.from_file("configs/agents/agent-registry.yaml")
    orchestrator = SupervisorOrchestrator(
        registry=registry,
        agent_manager=manager,
        repository=repository,
    )
    return orchestrator, repository


def test_agent_registry_loads_entries_and_rules() -> None:
    registry = AgentRegistry.from_file("configs/agents/agent-registry.yaml")
    agents = registry.list_agents()
    names = [item.name for item in agents]
    assert "flight-expert" in names
    assert "hotel-expert" in names
    assert "general-expert" in names

    decision = registry.resolve("flight_*")
    assert decision.mode == "single"
    assert decision.selected_agents == ["flight-expert"]


def test_intent_router_uses_registry_keywords_and_merges_intents() -> None:
    registry = AgentRegistry.from_file("configs/agents/agent-registry.yaml")
    router = IntentRouter()

    complex_decision = router.route("帮我看机票和酒店行程", registry)
    assert complex_decision.mode == "multi_agent_consultation"
    assert set(complex_decision.selected_agents) == {"flight-expert", "hotel-expert"}
    assert set(complex_decision.intent.split(",")) == {"flight_*", "hotel_*"}

    default_decision = router.route("今天天气如何", registry)
    assert default_decision.selected_agents == ["general-expert"]


def test_orchestrator_run_routes_to_multiple_workers() -> None:
    orchestrator, repository = _build_orchestrator()

    result = asyncio.run(
        orchestrator.run(
            goal="帮我查机票并推荐酒店",
            thread_id="thread-orch-1",
        )
    )

    assert result["status"] in {"completed", "failed"}
    assert len(result["delegations"]) == 2
    workers = {item["worker"] for item in result["delegations"]}
    assert workers == {"flight-expert", "hotel-expert"}

    trace = asyncio.run(repository.get_task_trace(result["task_id"]))
    task = asyncio.run(repository.get_task(result["task_id"]))
    assert trace is not None
    assert task is not None
    assert len(trace.steps) >= 2
    assert task.current_step == trace.steps[-1].step.step_index
    assert any(step.step.trace_meta.get("node_role") == "supervisor" for step in trace.steps)
    assert any(step.step.trace_meta.get("node_role") == "worker" for step in trace.steps)


def test_orchestrator_marks_task_failed_when_worker_initialization_breaks() -> None:
    orchestrator, repository = _build_orchestrator()

    async def broken_worker(_: str) -> str:
        raise ValueError("broken worker config")

    cast(Any, orchestrator)._ensure_worker_agent = broken_worker

    result = asyncio.run(
        orchestrator.run(
            goal="帮我查机票",
            thread_id="thread-orch-broken-worker",
        )
    )

    task = asyncio.run(repository.get_task(result["task_id"]))
    trace = asyncio.run(repository.get_task_trace(result["task_id"]))
    assert task is not None
    assert trace is not None
    assert result["status"] == "failed"
    assert task.status == "failed"
    assert task.current_step == trace.steps[-1].step.step_index
    worker_steps = [step for step in trace.steps if step.step.action_type == "delegate"]
    assert worker_steps
    assert worker_steps[0].step.result["error"]["code"] == "worker_run_error"


def test_orchestrator_api_routes(monkeypatch: MonkeyPatch) -> None:
    app = create_app()
    orchestrator, repository = _build_orchestrator()
    manager = AgentManager.for_tests(repository=repository)
    fake_resources = SimpleNamespace(
        db_engine=object(),
        redis_client=object(),
        runtime_checkpointer=RuntimeCheckpointer(in_memory=True),
        startup_health=SimpleNamespace(db=True, redis=True),
        orchestrator_manager=orchestrator,
    )

    async def fake_init_resources(_: object) -> object:
        return fake_resources

    async def fake_close_resources(_: object) -> None:
        return None

    monkeypatch.setattr(app_module, "init_resources", fake_init_resources, raising=False)
    monkeypatch.setattr(app_module, "close_resources", fake_close_resources, raising=False)

    with TestClient(app) as client:
        app.state.agent_manager = manager
        app.state.orchestrator_manager = orchestrator

        agents_response = client.get("/api/v1/orchestrator/agents")
        assert agents_response.status_code == 200
        payload = agents_response.json()
        assert payload["code"] == 1
        assert any(item["name"] == "flight-expert" for item in payload["data"])

        run_response = client.post(
            "/api/v1/orchestrator/run",
            json={"goal": "帮我查机票并推荐酒店", "thread_id": "thread-orch-api"},
        )
        assert run_response.status_code == 200
        run_payload = run_response.json()
        assert run_payload["code"] == 1
        assert len(run_payload["data"]["delegations"]) == 2
