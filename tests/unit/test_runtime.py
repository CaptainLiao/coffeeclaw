from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from src.core import app as app_module
from src.core.app import create_app
from src.runtime.checkpoint import RuntimeCheckpointer
from src.runtime.lifecycle import AgentConfigParser, AgentManager
from src.runtime.repository import InMemoryRuntimeRepository
from src.services import health as health_service

CONFIG_PATH = Path("configs/agents/demo-agent.md")


async def always_healthy(_: object) -> bool:
    return True


@pytest.mark.asyncio
async def test_agent_config_parser_reads_demo_agent() -> None:
    config = AgentConfigParser.parse(CONFIG_PATH)

    assert config.name == "demo-agent"
    assert config.model.primary == "gpt-4o"
    assert config.policy.max_steps == 6
    assert "三步工具调用" in config.system_prompt


@pytest.mark.asyncio
async def test_agent_manager_runs_three_tool_steps_and_records_logs() -> None:
    repository = InMemoryRuntimeRepository()
    manager = AgentManager.for_tests(repository=repository)
    created = await manager.create_agent(config_path=str(CONFIG_PATH))

    result = await manager.run_agent(
        created["agent_id"],
        goal="Prepare a travel response",
        thread_id="thread-success",
    )

    task = await repository.get_task(result["task_id"])
    tool_logs = await repository.list_tool_logs(result["task_id"])

    assert result["status"] == "completed"
    assert result["step_count"] >= 4
    assert task is not None
    assert task.current_step == result["step_count"]
    assert len(tool_logs) == 3


@pytest.mark.asyncio
async def test_agent_manager_resume_continues_from_checkpoint() -> None:
    repository = InMemoryRuntimeRepository()
    manager = AgentManager.for_tests(
        repository=repository,
        checkpointer=RuntimeCheckpointer(in_memory=True),
    )
    created = await manager.create_agent(config_path=str(CONFIG_PATH))

    paused = await manager.run_agent(
        created["agent_id"],
        goal="Continue later",
        thread_id="thread-resume",
        stop_after_steps=1,
    )
    resumed = await manager.resume_agent(
        created["agent_id"],
        thread_id="thread-resume",
    )

    assert paused["status"] == "paused"
    assert paused["step_count"] == 1
    assert resumed["status"] == "completed"
    assert resumed["step_count"] > paused["step_count"]


@pytest.mark.asyncio
async def test_agent_manager_resume_rejects_completed_task() -> None:
    repository = InMemoryRuntimeRepository()
    manager = AgentManager.for_tests(repository=repository)
    created = await manager.create_agent(config_path=str(CONFIG_PATH))

    finished = await manager.run_agent(
        created["agent_id"],
        goal="Already done",
        thread_id="thread-finished",
    )

    assert finished["status"] == "completed"

    with pytest.raises(ValueError, match="cannot be resumed"):
        await manager.resume_agent(
            created["agent_id"],
            thread_id="thread-finished",
        )


@pytest.mark.asyncio
async def test_agent_manager_fails_when_max_steps_reached() -> None:
    repository = InMemoryRuntimeRepository()
    manager = AgentManager.for_tests(repository=repository)
    created = await manager.create_agent(
        inline_config={
            "name": "short-runner",
            "version": "0.1.0",
            "description": "short max steps",
            "model": {"primary": "gpt-4o", "fallback": "gpt-4o-mini"},
            "capabilities": {
                "tools": ["mcp://tools/mock-search@v1"],
                "mock_tool_steps": 5,
            },
            "memory": {"short_term": "redis"},
            "policy": {"max_steps": 2},
            "system_prompt": "Keep going.",
        }
    )

    result = await manager.run_agent(
        created["agent_id"],
        goal="Need many steps",
        thread_id="thread-max-steps",
    )

    assert result["status"] == "failed"
    assert result["step_count"] == 2


@pytest.mark.asyncio
async def test_run_agent_reuses_only_resumable_task() -> None:
    repository = InMemoryRuntimeRepository()
    manager = AgentManager.for_tests(repository=repository)
    created = await manager.create_agent(config_path=str(CONFIG_PATH))

    first = await manager.run_agent(
        created["agent_id"],
        goal="first run",
        thread_id="thread-rerun",
    )
    second = await manager.run_agent(
        created["agent_id"],
        goal="second run",
        thread_id="thread-rerun",
    )

    assert first["task_id"] != second["task_id"]


@pytest.mark.asyncio
async def test_run_agent_rejects_goal_change_on_same_resumable_thread() -> None:
    repository = InMemoryRuntimeRepository()
    manager = AgentManager.for_tests(repository=repository)
    created = await manager.create_agent(config_path=str(CONFIG_PATH))

    paused = await manager.run_agent(
        created["agent_id"],
        goal="first goal",
        thread_id="thread-goal-locked",
        stop_after_steps=1,
    )
    assert paused["status"] == "paused"

    with pytest.raises(ValueError, match="already has resumable task"):
        await manager.run_agent(
            created["agent_id"],
            goal="different goal",
            thread_id="thread-goal-locked",
        )


@pytest.mark.asyncio
async def test_memory_messages_do_not_duplicate_between_steps() -> None:
    repository = InMemoryRuntimeRepository()
    manager = AgentManager.for_tests(repository=repository)
    created = await manager.create_agent(config_path=str(CONFIG_PATH))

    paused = await manager.run_agent(
        created["agent_id"],
        goal="dedupe check",
        thread_id="thread-dedupe",
        stop_after_steps=1,
    )
    resumed = await manager.resume_agent(
        created["agent_id"],
        thread_id="thread-dedupe",
    )

    assert paused["status"] == "paused"
    assert resumed["status"] == "completed"
    human_messages = [message for message in resumed["messages"] if message["type"] == "human"]
    assert len(human_messages) == 1


@pytest.mark.asyncio
async def test_pause_agent_raises_for_missing_agent() -> None:
    manager = AgentManager.for_tests(repository=InMemoryRuntimeRepository())

    with pytest.raises(ValueError, match="not found"):
        await manager.pause_agent("missing-agent")


@pytest.mark.asyncio
async def test_repository_returns_task_trace_with_steps_and_logs() -> None:
    repository = InMemoryRuntimeRepository()
    manager = AgentManager.for_tests(repository=repository)
    created = await manager.create_agent(config_path=str(CONFIG_PATH))

    run_result = await manager.run_agent(
        created["agent_id"],
        goal="trace check",
        thread_id="thread-trace",
    )
    trace = await repository.get_task_trace(run_result["task_id"])

    assert trace is not None
    assert trace.task.id == run_result["task_id"]
    assert len(trace.steps) >= 1
    assert sum(len(step.tool_logs) for step in trace.steps) == 3


def test_agent_api_routes(monkeypatch: MonkeyPatch) -> None:
    app = create_app()
    manager = AgentManager.for_tests(repository=InMemoryRuntimeRepository())
    fake_resources = SimpleNamespace(
        db_engine=object(),
        redis_client=object(),
        runtime_checkpointer=RuntimeCheckpointer(in_memory=True),
        startup_health=SimpleNamespace(db=True, redis=True),
    )

    async def fake_init_resources(_: object) -> object:
        return fake_resources

    async def fake_close_resources(_: object) -> None:
        return None

    monkeypatch.setattr(app_module, "init_resources", fake_init_resources, raising=False)
    monkeypatch.setattr(app_module, "close_resources", fake_close_resources, raising=False)

    with TestClient(app) as client:
        app.state.agent_manager = manager
        response = client.post(
            "/api/v1/agents",
            json={"agent_config_path": str(CONFIG_PATH)},
        )
        assert response.status_code == 200
        agent_id = response.json()["agent_id"]

        run_response = client.post(
            f"/api/v1/agents/run?agent_id={agent_id}",
            json={"goal": "API runtime test", "thread_id": "thread-api"},
        )
        assert run_response.status_code == 200
        assert run_response.json()["status"] == "completed"

        status_response = client.get(f"/api/v1/agents/status?agent_id={agent_id}")
        assert status_response.status_code == 200
        assert status_response.json()["latest_task"]["thread_id"] == "thread-api"

        task_id = run_response.json()["task_id"]
        trace_response = client.get(f"/api/v1/tasks/{task_id}/trace")
        assert trace_response.status_code == 200
        trace_payload = trace_response.json()
        assert trace_payload["task"]["task_id"] == task_id
        assert len(trace_payload["steps"]) >= 1

        missing_trace = client.get("/api/v1/tasks/missing-task/trace")
        assert missing_trace.status_code == 404


def test_health_check_with_runtime_resources(monkeypatch: MonkeyPatch) -> None:
    app = create_app()
    fake_resources = SimpleNamespace(
        db_engine=object(),
        redis_client=object(),
        runtime_checkpointer=RuntimeCheckpointer(in_memory=True),
        startup_health=SimpleNamespace(db=True, redis=True),
    )

    async def fake_init_resources(_: object) -> object:
        return fake_resources

    async def fake_close_resources(_: object) -> None:
        return None

    monkeypatch.setattr(health_service, "check_db_connection", always_healthy)
    monkeypatch.setattr(health_service, "check_redis_connection", always_healthy)
    monkeypatch.setattr(app_module, "init_resources", fake_init_resources)
    monkeypatch.setattr(app_module, "close_resources", fake_close_resources)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
