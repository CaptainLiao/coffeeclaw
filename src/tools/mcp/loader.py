from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.tools.mcp.models import MCPToolDefinition


class MCPToolLoader:
    @staticmethod
    def from_json(path: str | Path) -> MCPToolDefinition:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return MCPToolLoader.from_dict(payload)

    @staticmethod
    def from_dict(data: dict[str, Any]) -> MCPToolDefinition:
        return MCPToolDefinition.model_validate(data)
