from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict, cast

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    messages_from_dict,
    messages_to_dict,
)
from redis.asyncio.client import Redis

from src.memory.shortterm import ShortTermMemory
from src.model import ModelResponse, ModelService


class ToolCall(TypedDict):
    id: str
    name: str
    arguments: dict[str, Any]


class ToolResult(TypedDict):
    tool_call_id: str
    tool_name: str
    success: bool
    output: dict[str, Any]
    error_message: str | None
    latency_ms: int


@dataclass(frozen=True)
class ThinkResult:
    tool_calls: list[ToolCall]
    final_response: str | None
    plan: dict[str, Any]
    model_used: str


class ShortTermMemoryAdapter(Protocol):
    async def load_context(self, thread_id: str) -> list[BaseMessage]:
        ...

    async def append_messages(self, thread_id: str, messages: list[BaseMessage]) -> None:
        ...


class ModelAdapter(Protocol):
    async def decide_next_action(
        self,
        state: dict[str, Any],
        available_tools: list[str],
    ) -> ThinkResult:
        ...

    async def summarize_reflection(self, state: dict[str, Any]) -> str:
        ...


class ToolExecutor(Protocol):
    async def list_tools(self, agent_config: dict[str, Any]) -> list[str]:
        ...

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        ...


class RedisShortTermMemoryAdapter:
    def __init__(self, redis_client: Redis) -> None:
        self._shortterm = ShortTermMemory(redis_client)

    async def load_context(self, thread_id: str) -> list[BaseMessage]:
        raw_messages = await self._shortterm.get_messages(thread_id, limit=50)
        messages: list[BaseMessage] = []
        for item in raw_messages:
            role = str(item.get("type", "human"))
            content = str(item.get("content", ""))
            if role == "ai":
                messages.append(AIMessage(content=content))
            elif role == "system":
                messages.append(SystemMessage(content=content))
            else:
                messages.append(HumanMessage(content=content))
        return messages

    async def append_messages(self, thread_id: str, messages: list[BaseMessage]) -> None:
        await self._shortterm.clear_session(thread_id)
        for message in messages:
            role = "human"
            if isinstance(message, AIMessage):
                role = "ai"
            elif isinstance(message, SystemMessage):
                role = "system"
            await self._shortterm.append_message(
                thread_id,
                {"type": role, "content": str(message.content)},
            )


class InMemoryShortTermMemoryAdapter:
    def __init__(self) -> None:
        self._store: dict[str, list[dict[str, Any]]] = {}

    async def load_context(self, thread_id: str) -> list[BaseMessage]:
        return list(messages_from_dict(self._store.get(thread_id, [])))

    async def append_messages(self, thread_id: str, messages: list[BaseMessage]) -> None:
        self._store[thread_id] = messages_to_dict(messages)


class MockModelAdapter:
    def __init__(self, default_model: str = "mock-runtime-model") -> None:
        self._default_model = default_model

    async def decide_next_action(
        self,
        state: dict[str, Any],
        available_tools: list[str],
    ) -> ThinkResult:
        agent_config = cast(dict[str, Any], state["agent_config"])
        capabilities = cast(dict[str, Any], agent_config.get("capabilities", {}))
        planned_steps = int(capabilities.get("mock_tool_steps", 3))
        current_step = int(state.get("step_count", 0))
        goal = cast(str, state["goal"])

        if current_step >= planned_steps:
            final_response = f"Task completed for goal: {goal}"
            return ThinkResult(
                tool_calls=[],
                final_response=final_response,
                plan={"decision": "respond", "reason": "planned steps completed"},
                model_used=self._default_model,
            )

        tool_name = (
            available_tools[min(current_step, len(available_tools) - 1)]
            if available_tools
            else "mock_tool"
        )
        tool_call: ToolCall = {
            "id": str(uuid.uuid4()),
            "name": tool_name,
            "arguments": {
                "goal": goal,
                "step": current_step + 1,
                "memory_context": cast(str, state.get("memory_context", "")),
            },
        }
        return ThinkResult(
            tool_calls=[tool_call],
            final_response=None,
            plan={"decision": "tool_call", "tool_name": tool_name, "step": current_step + 1},
            model_used=self._default_model,
        )

    async def summarize_reflection(self, state: dict[str, Any]) -> str:
        status = cast(str, state["status"])
        step_count = int(state["step_count"])
        if status == "completed":
            return f"Completed after {step_count} steps."
        if status == "failed":
            return f"Failed after {step_count} steps."
        if status == "escalate":
            return f"Escalation requested after {step_count} steps."
        return f"Continuing after {step_count} steps."


class LiteLLMModelAdapter:
    def __init__(self, *, model_service: ModelService, default_model: str = "gpt-4o") -> None:
        self._model_service = model_service
        self._default_model = default_model

    def has_any_key(self) -> bool:
        return self._model_service.has_any_key()

    async def decide_next_action(
        self,
        state: dict[str, Any],
        available_tools: list[str],
    ) -> ThinkResult:
        llm_messages = self._to_litellm_messages(cast(list[BaseMessage], state["messages"]))
        tool_defs = self._build_tool_defs(available_tools)

        response = await self._model_service.think(
            agent_config=cast(dict[str, Any], state["agent_config"]),
            messages=llm_messages,
            tools=tool_defs,
            tool_results=cast(list[dict[str, Any]], state.get("tool_results", [])),
        )
        return self._to_think_result(response)

    async def summarize_reflection(self, state: dict[str, Any]) -> str:
        status = cast(str, state["status"])
        step_count = int(state["step_count"])
        if status == "completed":
            return f"Completed after {step_count} steps."
        if status == "failed":
            return f"Failed after {step_count} steps."
        if status == "escalate":
            return f"Escalation requested after {step_count} steps."
        return f"Continuing after {step_count} steps."

    def _to_litellm_messages(self, messages: list[BaseMessage]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for message in messages:
            if isinstance(message, HumanMessage):
                result.append({"role": "user", "content": str(message.content)})
                continue
            if isinstance(message, SystemMessage):
                result.append({"role": "system", "content": str(message.content)})
                continue
            if isinstance(message, ToolMessage):
                result.append(
                    {
                        "role": "tool",
                        "content": str(message.content),
                        "tool_call_id": message.tool_call_id,
                    }
                )
                continue

            payload: dict[str, Any] = {"role": "assistant", "content": str(message.content)}
            if isinstance(message, AIMessage) and message.tool_calls:
                payload["tool_calls"] = [
                    {
                        "id": str(tool_call.get("id", "")),
                        "type": "function",
                        "function": {
                            "name": str(tool_call.get("name", "")),
                            "arguments": json.dumps(tool_call.get("args", {}), ensure_ascii=False),
                        },
                    }
                    for tool_call in message.tool_calls
                ]
            result.append(payload)
        return result

    def _build_tool_defs(self, available_tools: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": f"Execute tool {tool_name}",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": True,
                    },
                },
            }
            for tool_name in available_tools
        ]

    def _to_think_result(self, response: ModelResponse) -> ThinkResult:
        tool_calls: list[ToolCall] = []
        for item in response.tool_calls:
            tool_calls.append(
                ToolCall(
                    id=item.id or str(uuid.uuid4()),
                    name=item.name,
                    arguments=item.arguments,
                )
            )

        return ThinkResult(
            tool_calls=tool_calls,
            final_response=response.final_response,
            plan={
                **response.plan,
                "warnings": response.warnings,
                "model_cost_usd": response.model_cost_usd,
                "token_usage": response.token_usage,
            },
            model_used=response.model_used or self._default_model,
        )


class MockToolExecutor:
    async def list_tools(self, agent_config: dict[str, Any]) -> list[str]:
        capabilities = cast(dict[str, Any], agent_config.get("capabilities", {}))
        tools = capabilities.get("tools", [])
        if isinstance(tools, list) and tools:
            return [str(tool).split("/")[-1].split("@")[0] for tool in tools]
        return ["mock_tool_a", "mock_tool_b", "mock_tool_c"]

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        started_at = time.perf_counter()
        goal = str(tool_call["arguments"].get("goal", ""))
        should_fail = (
            "fail_tool" in goal.lower()
            and int(tool_call["arguments"].get("step", 0)) >= 2
        )

        if should_fail:
            return ToolResult(
                tool_call_id=tool_call["id"],
                tool_name=tool_call["name"],
                success=False,
                output={"message": "Mock tool execution failed."},
                error_message="mock tool failure requested by goal",
                latency_ms=int((time.perf_counter() - started_at) * 1000),
            )

        return ToolResult(
            tool_call_id=tool_call["id"],
            tool_name=tool_call["name"],
            success=True,
            output={
                "message": f"Executed {tool_call['name']}",
                "step": tool_call["arguments"].get("step"),
            },
            error_message=None,
            latency_ms=int((time.perf_counter() - started_at) * 1000),
        )


def build_tool_messages(results: list[ToolResult]) -> list[ToolMessage]:
    tool_messages: list[ToolMessage] = []
    for result in results:
        tool_messages.append(
            ToolMessage(
                content=json.dumps(result["output"]),
                tool_call_id=result["tool_call_id"],
                name=result["tool_name"],
                status="success" if result["success"] else "error",
            )
        )
    return tool_messages


def build_think_message(result: ThinkResult) -> AIMessage:
    if result.final_response is not None:
        return AIMessage(content=result.final_response)

    tool_calls_payload = [
        {
            "id": tool_call["id"],
            "name": tool_call["name"],
            "args": tool_call["arguments"],
        }
        for tool_call in result.tool_calls
    ]
    return AIMessage(content="Planning tool calls.", tool_calls=tool_calls_payload)
