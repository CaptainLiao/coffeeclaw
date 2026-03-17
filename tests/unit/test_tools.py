from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.core import app as app_module
from src.core.app import create_app
from src.runtime.checkpoint import RuntimeCheckpointer
from src.runtime.lifecycle import AgentManager
from src.runtime.repository import InMemoryRuntimeRepository
from src.tools import ToolCaller
from src.tools.docker import ToolExecutorFactory
from src.tools.mcp import MCPToolDefinition
from src.tools.registry import ToolRegistry
from src.tools.skills import SkillManager


def _build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.load_from_dir("configs/tools")
    return registry


def test_tool_registry_loads_all_tool_definitions() -> None:
    registry = _build_registry()
    names = [item.name for item in registry.list_all()]
    assert "echo" in names
    assert "http-request" in names
    assert "mock-search" in names


def test_tool_caller_executes_echo_tool() -> None:
    caller = ToolCaller(registry=_build_registry(), executor_factory=ToolExecutorFactory())
    result = asyncio.run(
        caller.call(
            tool_name="echo",
            input_params={"message": "hello"},
            agent_config={"policy": {"blocked_actions": []}},
        )
    )
    assert result.success is True
    assert result.output is not None
    assert result.output["echo"]["message"] == "hello"


def test_tool_caller_rejects_blocked_action() -> None:
    caller = ToolCaller(registry=_build_registry(), executor_factory=ToolExecutorFactory())
    result = asyncio.run(
        caller.call(
            tool_name="echo",
            input_params={"message": "hello"},
            agent_config={"policy": {"blocked_actions": ["echo"]}},
        )
    )
    assert result.success is False
    assert result.error is not None
    assert "blocked by policy" in result.error


def test_tool_caller_accepts_mock_search_query_payload() -> None:
    caller = ToolCaller(registry=_build_registry(), executor_factory=ToolExecutorFactory())
    result = asyncio.run(
        caller.call(
            tool_name="mock-search",
            input_params={"query": "北京天气"},
            agent_config={"policy": {"blocked_actions": []}},
        )
    )
    assert result.success is True


def test_tool_caller_accepts_mock_plan_question_payload() -> None:
    caller = ToolCaller(registry=_build_registry(), executor_factory=ToolExecutorFactory())
    result = asyncio.run(
        caller.call(
            tool_name="mock-plan",
            input_params={"question": "帮我规划出行", "need_info": ["出发地", "日期"]},
            agent_config={"policy": {"blocked_actions": []}},
        )
    )
    assert result.success is True


def test_skill_manager_injects_prompt() -> None:
    manager = SkillManager()
    manager.load_from_dir("configs/skills")
    merged = manager.inject_into_context("demo-skill", "You are an agent.")
    assert "[Skill: demo-skill]" in merged
    assert "SOP" in merged


def test_docker_tool_executor_smoke() -> None:
    tool_def = MCPToolDefinition.model_validate(
        {
            "name": "docker-smoke",
            "version": "1.0.0",
            "description": "smoke",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
            "execution": {"sandbox": "docker"},
        }
    )
    factory = ToolExecutorFactory()
    executor = factory.get("docker")
    result = asyncio.run(executor.execute(tool_def, {"ping": "pong"}))
    assert result["sandbox"] == "docker"
    assert result["tool"] == "docker-smoke"


def test_tools_and_skills_api_routes(monkeypatch: pytest.MonkeyPatch) -> None:
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

        tools_response = client.get("/api/v1/tools")
        assert tools_response.status_code == 200
        tools_data = tools_response.json()["data"]
        assert any(item["name"] == "echo" for item in tools_data)

        tool_detail = client.get("/api/v1/tools/echo")
        assert tool_detail.status_code == 200
        assert tool_detail.json()["data"]["name"] == "echo"

        tool_test = client.post(
            "/api/v1/tools/echo/test",
            json={"input_params": {"message": "api"}},
        )
        assert tool_test.status_code == 200
        assert tool_test.json()["data"]["success"] is True

        skills_response = client.get("/api/v1/skills")
        assert skills_response.status_code == 200
        skills_data = skills_response.json()["data"]
        assert any(item["name"] == "demo-skill" for item in skills_data)
