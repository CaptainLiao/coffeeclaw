from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from jsonschema import ValidationError, validate

from src.tools.docker import ToolExecutionError, ToolExecutorFactory
from src.tools.registry import ToolRegistry


@dataclass(frozen=True)
class ToolResult:
    success: bool
    output: dict[str, Any] | None
    error: str | None
    latency_ms: int


class ToolCaller:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        executor_factory: ToolExecutorFactory | None = None,
    ) -> None:
        self._registry = registry
        self._executor_factory = executor_factory or ToolExecutorFactory()

    def list_for_agent(self, agent_config: dict[str, Any]) -> list[str]:
        return [item.name for item in self._registry.list_for_agent(agent_config)]

    def list_tools(self) -> list[dict[str, Any]]:
        return [item.model_dump() for item in self._registry.list_all()]

    def get_tool(self, tool_name: str) -> dict[str, Any] | None:
        tool = self._registry.get(tool_name)
        if tool is None:
            return None
        return tool.model_dump()

    async def call(
        self,
        *,
        tool_name: str,
        input_params: dict[str, Any],
        agent_config: dict[str, Any],
    ) -> ToolResult:
        started_at = time.perf_counter()
        tool_def = self._registry.get(tool_name)
        if tool_def is None:
            return ToolResult(
                success=False,
                output=None,
                error=f"Tool {tool_name} is not registered.",
                latency_ms=int((time.perf_counter() - started_at) * 1000),
            )

        blocked = agent_config.get("policy", {}).get("blocked_actions", [])
        if isinstance(blocked, list) and tool_name in {str(item) for item in blocked}:
            return ToolResult(
                success=False,
                output=None,
                error=f"Tool {tool_name} is blocked by policy.",
                latency_ms=int((time.perf_counter() - started_at) * 1000),
            )

        try:
            validate(instance=input_params, schema=tool_def.input_schema)
        except ValidationError as exc:
            return ToolResult(
                success=False,
                output=None,
                error=f"Input validation failed: {exc.message}",
                latency_ms=int((time.perf_counter() - started_at) * 1000),
            )

        executor = self._executor_factory.get(tool_def.execution.sandbox)
        try:
            output = await executor.execute(tool_def, input_params, credentials=None)
            return ToolResult(
                success=True,
                output=output,
                error=None,
                latency_ms=int((time.perf_counter() - started_at) * 1000),
            )
        except ToolExecutionError as exc:
            return ToolResult(
                success=False,
                output=None,
                error=str(exc),
                latency_ms=int((time.perf_counter() - started_at) * 1000),
            )
