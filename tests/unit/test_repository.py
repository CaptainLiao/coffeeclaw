from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from src.runtime.repository import InMemoryRuntimeRepository, SqlRuntimeRepository


@pytest.mark.asyncio
async def test_inmemory_repository_rejects_missing_task_on_status_update() -> None:
    repository = InMemoryRuntimeRepository()

    with pytest.raises(ValueError, match="Task missing-task not found"):
        await repository.update_task_status(
            "missing-task",
            status="failed",
            current_step=1,
            completed=True,
        )


@pytest.mark.asyncio
async def test_inmemory_repository_rejects_missing_step_on_tool_log_creation() -> None:
    repository = InMemoryRuntimeRepository()

    with pytest.raises(ValueError, match="Task step missing-step not found"):
        await repository.create_tool_log(
            task_step_id="missing-step",
            tool_name="mock-search",
            input_params={"query": "coffee"},
            output_result={},
            latency_ms=1,
            success=False,
            error_message="missing",
        )


@pytest.mark.asyncio
async def test_inmemory_repository_tracks_task_id_for_tool_logs() -> None:
    repository = InMemoryRuntimeRepository()
    task = await repository.create_task(
        agent_id="agent-1",
        goal="test",
        thread_id="thread-1",
        status="running",
    )
    step = await repository.create_task_step(
        task_id=task.id,
        step_index=1,
        action_type="tool_call",
        plan={"tool": "mock-search"},
        result={},
        model_used="test-model",
    )

    log = await repository.create_tool_log(
        task_step_id=step.id,
        tool_name="mock-search",
        input_params={"query": "coffee"},
        output_result={"items": []},
        latency_ms=1,
        success=True,
        error_message=None,
    )

    assert await repository.list_tool_logs(task.id) == [log]


@dataclass
class _FakeResult:
    rowcount: int | None


class _FakeConnection:
    def __init__(self, result: _FakeResult) -> None:
        self._result = result

    async def execute(self, *_args: Any, **_kwargs: Any) -> _FakeResult:
        return self._result


class _FakeBeginContext:
    def __init__(self, result: _FakeResult) -> None:
        self._connection = _FakeConnection(result)

    async def __aenter__(self) -> _FakeConnection:
        return self._connection

    async def __aexit__(self, *_args: Any) -> None:
        return None


class _FakeEngine:
    def __init__(self, rowcount: int | None) -> None:
        self._result = _FakeResult(rowcount=rowcount)

    def begin(self) -> _FakeBeginContext:
        return _FakeBeginContext(self._result)


@pytest.mark.asyncio
async def test_sql_repository_rejects_missing_task_on_status_update() -> None:
    repository = SqlRuntimeRepository(_FakeEngine(rowcount=0))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="Task missing-task not found"):
        await repository.update_task_status(
            "missing-task",
            status="failed",
            current_step=1,
            completed=True,
        )
