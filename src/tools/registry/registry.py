from __future__ import annotations

from pathlib import Path
from typing import Any

from src.tools.mcp import MCPToolDefinition, MCPToolLoader


def _parse_tool_name(tool_ref: str) -> str:
    name = tool_ref.strip()
    if "://" in name:
        name = name.split("://", maxsplit=1)[1]
    if "/" in name:
        name = name.rsplit("/", maxsplit=1)[1]
    if "@" in name:
        name = name.split("@", maxsplit=1)[0]
    return name


class ToolRegistry:
    _instance: "ToolRegistry | None" = None

    def __init__(self) -> None:
        self._tools: dict[str, MCPToolDefinition] = {}

    @classmethod
    def instance(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = ToolRegistry()
        return cls._instance

    @classmethod
    def reset_for_tests(cls) -> None:
        cls._instance = None

    def register(self, tool_def: MCPToolDefinition) -> None:
        self._tools[tool_def.name] = tool_def

    def get(self, tool_name: str) -> MCPToolDefinition | None:
        return self._tools.get(tool_name)

    def list_all(self) -> list[MCPToolDefinition]:
        return sorted(self._tools.values(), key=lambda item: item.name)

    def list_for_agent(self, agent_config: dict[str, Any]) -> list[MCPToolDefinition]:
        capabilities = agent_config.get("capabilities", {})
        if not isinstance(capabilities, dict):
            return self.list_all()
        raw_tools = capabilities.get("tools", [])
        if not isinstance(raw_tools, list) or not raw_tools:
            return self.list_all()

        allowed_names = {_parse_tool_name(str(item)) for item in raw_tools}
        return [
            tool_def
            for tool_def in self.list_all()
            if tool_def.name in allowed_names
        ]

    def load_from_dir(self, dir_path: str | Path) -> None:
        base = Path(dir_path)
        if not base.exists():
            return
        for json_path in sorted(base.glob("*.json")):
            tool_def = MCPToolLoader.from_json(json_path)
            self.register(tool_def)
