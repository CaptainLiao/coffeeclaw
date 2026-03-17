from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Protocol

from src.tools.mcp import MCPToolDefinition


class ToolExecutionError(RuntimeError):
    pass


class ToolExecutorProtocol(Protocol):
    async def execute(
        self,
        tool_def: MCPToolDefinition,
        input_params: dict[str, Any],
        credentials: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        ...


class LocalToolExecutor:
    async def execute(
        self,
        tool_def: MCPToolDefinition,
        input_params: dict[str, Any],
        credentials: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        _ = credentials
        if tool_def.name == "echo":
            return {"echo": input_params}
        if tool_def.name == "http-request":
            method = str(input_params.get("method", "GET")).upper()
            url = str(input_params.get("url", ""))
            return {
                "mocked": True,
                "method": method,
                "url": url,
                "status_code": 200,
                "body": {"message": "mock http response"},
            }
        return {"ok": True, "tool": tool_def.name, "input": input_params}


class DockerToolExecutor:
    async def execute(
        self,
        tool_def: MCPToolDefinition,
        input_params: dict[str, Any],
        credentials: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        # v1 先提供可替换实现，默认复用本地执行语义，避免阻塞主链路联调。
        _ = credentials
        await asyncio.sleep(0)
        return {
            "sandbox": "docker",
            "tool": tool_def.name,
            "input": input_params,
            "mocked": True,
        }


class ToolExecutorFactory:
    def __init__(self) -> None:
        self._local = LocalToolExecutor()
        self._docker = DockerToolExecutor()

    def get(self, sandbox_type: str) -> ToolExecutorProtocol:
        if sandbox_type == "docker":
            return self._docker
        return self._local
