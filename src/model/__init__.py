from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from src.model.provider import ModelProvider, TokenTracker
from src.model.router import BasicRouter
from src.model.safety import InputFilter, OutputFilter


@dataclass(frozen=True)
class ModelToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelResponse:
    tool_calls: list[ModelToolCall]
    final_response: str | None
    model_used: str
    token_usage: dict[str, Any]
    model_cost_usd: float
    warnings: list[str]
    plan: dict[str, Any]


class ModelService:
    def __init__(
        self,
        *,
        provider: ModelProvider,
        input_filter: InputFilter,
        output_filter: OutputFilter,
    ) -> None:
        self._provider = provider
        self._input_filter = input_filter
        self._output_filter = output_filter

    def has_any_key(self) -> bool:
        return self._provider.has_any_key()

    async def think(
        self,
        *,
        agent_config: dict[str, Any],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        tool_results: list[dict[str, Any]] | None,
    ) -> ModelResponse:
        model_cfg = agent_config.get("model", {})
        primary = str(model_cfg.get("primary", "gpt-4o"))
        fallback = str(model_cfg.get("fallback", primary))
        router = BasicRouter(provider=self._provider, primary=primary, fallback=fallback)

        filtered_messages = self._input_filter.check(messages)
        completion = await router.call(messages=filtered_messages, tools=tools)
        model_used = self._extract_model(completion, primary)
        output_message = self._extract_message(completion)
        tool_calls = self._extract_tool_calls(output_message)
        output_text = self._extract_content(output_message)
        output_check = await self._output_filter.check(
            response_text=output_text,
            tool_results=tool_results,
        )

        usage = TokenTracker.from_completion(completion)
        return ModelResponse(
            tool_calls=tool_calls,
            final_response=None if tool_calls else output_text,
            model_used=model_used,
            token_usage=usage.model_dump(),
            model_cost_usd=TokenTracker.get_cost(model_used, usage),
            warnings=list(output_check.get("warnings", [])),
            plan=self._build_plan(tool_calls, output_text),
        )

    def _extract_model(self, completion: Any, default_model: str) -> str:
        model = getattr(completion, "model", None)
        if isinstance(model, str):
            return model
        if isinstance(completion, dict) and isinstance(completion.get("model"), str):
            return str(completion["model"])
        return default_model

    def _extract_message(self, completion: Any) -> dict[str, Any]:
        if isinstance(completion, dict):
            choices = completion.get("choices", [])
            if choices:
                message = choices[0].get("message", {})
                return message if isinstance(message, dict) else {}

        choices = getattr(completion, "choices", None)
        if not choices:
            return {}
        message = getattr(choices[0], "message", None)
        if message is None:
            return {}
        if isinstance(message, dict):
            return message
        return {
            "content": getattr(message, "content", ""),
            "tool_calls": getattr(message, "tool_calls", []),
        }

    def _extract_tool_calls(self, message: dict[str, Any]) -> list[ModelToolCall]:
        raw_tool_calls = message.get("tool_calls") or []
        tool_calls: list[ModelToolCall] = []
        for item in raw_tool_calls:
            item_payload = item if isinstance(item, dict) else {
                "id": getattr(item, "id", ""),
                "function": getattr(item, "function", {}),
            }
            function_payload = item_payload.get("function", {})
            if not isinstance(function_payload, dict):
                function_payload = {
                    "name": getattr(function_payload, "name", ""),
                    "arguments": getattr(function_payload, "arguments", {}),
                }
            arguments_raw = function_payload.get("arguments", {})
            arguments: dict[str, Any]
            if isinstance(arguments_raw, dict):
                arguments = arguments_raw
            elif isinstance(arguments_raw, str):
                try:
                    parsed = json.loads(arguments_raw)
                    arguments = parsed if isinstance(parsed, dict) else {"raw": arguments_raw}
                except json.JSONDecodeError:
                    arguments = {"raw": arguments_raw}
            else:
                arguments = {"raw": str(arguments_raw)}
            tool_calls.append(
                ModelToolCall(
                    id=str(item_payload.get("id", "")),
                    name=str(function_payload.get("name", "")),
                    arguments=arguments,
                )
            )
        return [call for call in tool_calls if call.id and call.name]

    def _extract_content(self, message: dict[str, Any]) -> str:
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts: list[str] = []
            for chunk in content:
                if isinstance(chunk, dict) and "text" in chunk:
                    texts.append(str(chunk["text"]))
            return "\n".join(texts)
        return str(content)

    def _build_plan(self, tool_calls: list[ModelToolCall], output_text: str) -> dict[str, Any]:
        if tool_calls:
            return {
                "decision": "tool_call",
                "tools": [tool.name for tool in tool_calls],
            }
        return {
            "decision": "respond",
            "summary": output_text[:200],
        }
