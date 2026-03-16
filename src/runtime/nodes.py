from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from langchain_core.messages import HumanMessage, messages_to_dict

from src.runtime.adapters import (
    ModelAdapter,
    ShortTermMemoryAdapter,
    ToolCall,
    ToolExecutor,
    ToolResult,
    build_think_message,
    build_tool_messages,
)
from src.runtime.repository import RuntimeRepository


@dataclass(frozen=True)
class RuntimeNodeServices:
    memory: ShortTermMemoryAdapter
    model: ModelAdapter
    tools: ToolExecutor
    repository: RuntimeRepository


NodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _truncate_messages(messages: list[Any], max_messages: int = 10) -> list[Any]:
    if len(messages) <= max_messages:
        return messages
    return messages[-max_messages:]


def create_sense_node(services: RuntimeNodeServices) -> NodeFn:
    async def sense_node(state: dict[str, Any]) -> dict[str, Any]:
        thread_id = cast(str, state["thread_id"])
        memory_messages = await services.memory.load_context(thread_id)
        current_messages = cast(list[Any], state.get("messages", []))
        if not current_messages:
            if memory_messages:
                current_messages = memory_messages
            else:
                current_messages = [HumanMessage(content=cast(str, state["goal"]))]

        merged_messages = _truncate_messages(current_messages)
        memory_context = "\n".join(str(message.content) for message in merged_messages[-5:])
        return {
            "messages": merged_messages,
            "memory_context": memory_context,
        }

    return sense_node


def create_think_node(services: RuntimeNodeServices) -> NodeFn:
    async def think_node(state: dict[str, Any]) -> dict[str, Any]:
        available_tools = await services.tools.list_tools(
            cast(dict[str, Any], state["agent_config"])
        )
        decision = await services.model.decide_next_action(state, available_tools)
        token_usage = {}
        if isinstance(decision.plan, dict):
            raw_usage = decision.plan.get("token_usage", {})
            if isinstance(raw_usage, dict):
                token_usage = raw_usage
        messages = cast(list[Any], state["messages"]) + [build_think_message(decision)]
        return {
            "messages": messages,
            "tool_calls": decision.tool_calls,
            "tool_results": [],
            "last_plan": decision.plan,
            "last_action": "respond" if decision.final_response is not None else "tool_call",
            "model_used": decision.model_used,
            "token_usage": token_usage,
        }

    return think_node


def create_act_node(services: RuntimeNodeServices) -> NodeFn:
    async def act_node(state: dict[str, Any]) -> dict[str, Any]:
        tool_calls = cast(list[dict[str, Any]], state.get("tool_calls", []))
        if not tool_calls:
            return {"tool_results": [], "messages": cast(list[Any], state["messages"])}

        results: list[ToolResult] = []
        for tool_call in tool_calls:
            results.append(await services.tools.execute(cast(ToolCall, tool_call)))

        messages = cast(list[Any], state["messages"]) + build_tool_messages(results)
        return {
            "tool_results": results,
            "messages": messages,
        }

    return act_node


def create_reflect_node(services: RuntimeNodeServices) -> NodeFn:
    async def reflect_node(state: dict[str, Any]) -> dict[str, Any]:
        step_count = int(state.get("step_count", 0)) + 1
        goal = cast(str, state["goal"])
        tool_results = cast(list[ToolResult], state.get("tool_results", []))
        max_steps = int(
            cast(dict[str, Any], state["agent_config"]).get("policy", {}).get("max_steps", 50)
        )

        status = "running"
        if any(not result["success"] for result in tool_results):
            status = "failed"
        elif "escalate" in goal.lower() and step_count >= 2:
            status = "escalate"
        elif not cast(list[dict[str, Any]], state.get("tool_calls", [])):
            status = "completed"
        elif step_count >= max_steps:
            status = "failed"

        updated_state = dict(state)
        updated_state["step_count"] = step_count
        updated_state["status"] = status
        reflection = await services.model.summarize_reflection(updated_state)

        task_step = await services.repository.create_task_step(
            task_id=cast(str, state["task_id"]),
            step_index=step_count,
            action_type=cast(str, state.get("last_action", "tool_call")),
            plan=cast(dict[str, Any], state.get("last_plan", {})),
            result={
                "status": status,
                "reflection": reflection,
                "tool_results": tool_results,
                "messages": messages_to_dict(cast(list[Any], state["messages"])[-4:]),
            },
            model_used=cast(str, state.get("model_used", "mock-runtime-model")),
            token_usage=cast(dict[str, Any], state.get("token_usage", {})),
        )

        for tool_call, tool_result in zip(
            cast(list[dict[str, Any]], state.get("tool_calls", [])),
            tool_results,
            strict=False,
        ):
            await services.repository.create_tool_log(
                task_step_id=task_step.id,
                tool_name=tool_result["tool_name"],
                input_params=cast(dict[str, Any], tool_call["arguments"]),
                output_result=tool_result["output"],
                latency_ms=tool_result["latency_ms"],
                success=tool_result["success"],
                error_message=tool_result["error_message"],
            )

        await services.memory.append_messages(
            cast(str, state["thread_id"]),
            _truncate_messages(cast(list[Any], state["messages"]), max_messages=12),
        )

        return {
            "step_count": step_count,
            "status": status,
            "reflection": reflection,
        }

    return reflect_node
