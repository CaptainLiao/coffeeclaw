from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RetryConfig(BaseModel):
    max_attempts: int = 0
    backoff_ms: int = 200


class ExecutionConfig(BaseModel):
    timeout_ms: int = 5000
    retry: RetryConfig = Field(default_factory=RetryConfig)
    fallback: str | None = None
    sandbox: str = "process"
    required_permissions: list[str] = Field(default_factory=list)


class MCPToolDefinition(BaseModel):
    name: str
    version: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
