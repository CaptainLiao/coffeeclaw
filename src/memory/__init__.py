from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.memory.shortterm import ShortTermMemory
from src.runtime.repository import RuntimeRepository, TaskStepRecord, ToolLogRecord


@dataclass(frozen=True)
class TaskStepData:
    step_index: int
    action_type: str
    plan: dict[str, Any]
    result: dict[str, Any]
    model_used: str


@dataclass(frozen=True)
class ToolLogData:
    tool_name: str
    input_params: dict[str, Any]
    output_result: dict[str, Any]
    latency_ms: int
    success: bool
    error_message: str | None = None


class MemoryManager:
    def __init__(self, *, short_term: ShortTermMemory, repository: RuntimeRepository) -> None:
        self._short_term = short_term
        self._repository = repository

    async def save_turn(self, session_id: str, user_msg: str, assistant_msg: str) -> None:
        await self._short_term.append_message(
            session_id,
            {"type": "human", "content": user_msg},
        )
        await self._short_term.append_message(
            session_id,
            {"type": "ai", "content": assistant_msg},
        )

    async def load_context(self, session_id: str, max_tokens: int) -> list[dict[str, Any]]:
        return await self._short_term.get_context_within_budget(session_id, max_tokens=max_tokens)

    async def persist_step(self, task_id: str, step_data: TaskStepData) -> TaskStepRecord:
        return await self._repository.create_task_step(
            task_id=task_id,
            step_index=step_data.step_index,
            action_type=step_data.action_type,
            plan=step_data.plan,
            result=step_data.result,
            model_used=step_data.model_used,
        )

    async def persist_tool_log(self, step_id: str, log_data: ToolLogData) -> ToolLogRecord:
        return await self._repository.create_tool_log(
            task_step_id=step_id,
            tool_name=log_data.tool_name,
            input_params=log_data.input_params,
            output_result=log_data.output_result,
            latency_ms=log_data.latency_ms,
            success=log_data.success,
            error_message=log_data.error_message,
        )
