from __future__ import annotations

from typing import Any, TypedDict, cast

from langchain_core.messages import BaseMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.runtime.checkpoint import RuntimeCheckpointer
from src.runtime.nodes import (
    RuntimeNodeServices,
    create_act_node,
    create_reflect_node,
    create_sense_node,
    create_think_node,
)


class AgentState(TypedDict):
    messages: list[BaseMessage]
    goal: str
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    step_count: int
    reflection: str
    status: str
    agent_config: dict[str, Any]
    memory_context: str
    agent_id: str
    task_id: str
    thread_id: str
    last_action: str
    last_plan: dict[str, Any]
    model_used: str


def route_after_act(_: AgentState) -> str:
    return "reflect"


def route_after_reflect(state: AgentState) -> str:
    if state["status"] in {"completed", "failed", "escalate"}:
        return END
    return "sense"


def build_agent_graph(
    agent_config: dict[str, Any],
    runtime_services: RuntimeNodeServices,
    checkpointer: RuntimeCheckpointer,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    _ = agent_config
    graph = StateGraph(AgentState)
    graph.add_node("sense", cast(Any, create_sense_node(runtime_services)))
    graph.add_node("think", cast(Any, create_think_node(runtime_services)))
    graph.add_node("act", cast(Any, create_act_node(runtime_services)))
    graph.add_node("reflect", cast(Any, create_reflect_node(runtime_services)))
    graph.set_entry_point("sense")
    graph.add_edge("sense", "think")
    graph.add_edge("think", "act")
    graph.add_conditional_edges("act", route_after_act, {"reflect": "reflect"})
    graph.add_conditional_edges("reflect", route_after_reflect, {"sense": "sense", END: END})
    return graph.compile(
        checkpointer=checkpointer.get_checkpointer(),
        interrupt_after=["reflect"],
    )
