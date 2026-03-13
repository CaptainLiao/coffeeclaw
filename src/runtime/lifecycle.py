from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]
from langchain_core.messages import HumanMessage, messages_to_dict
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio.client import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from src.core.config import Settings, settings
from src.runtime.adapters import (
    InMemoryShortTermMemoryAdapter,
    MockModelAdapter,
    MockToolExecutor,
    RedisShortTermMemoryAdapter,
    ShortTermMemoryAdapter,
)
from src.runtime.checkpoint import RuntimeCheckpointer
from src.runtime.graph import AgentState, build_agent_graph
from src.runtime.nodes import RuntimeNodeServices
from src.runtime.repository import (
    InMemoryRuntimeRepository,
    RuntimeRepository,
    SqlRuntimeRepository,
)

FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


class ModelConfig(BaseModel):
    primary: str
    fallback: str
    routing_strategy: str = "cost_optimized"


class PolicyConfig(BaseModel):
    sandbox: str = "docker"
    max_steps: int = 50
    max_tool_calls: int = 20
    escalation_threshold: float = 0.6
    allowed_domains: list[str] = Field(default_factory=list)
    blocked_actions: list[str] = Field(default_factory=list)


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    version: str
    description: str
    model: ModelConfig
    capabilities: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    system_prompt: str


class AgentConfigParser:
    @staticmethod
    def parse(agent_md_path: str | Path) -> AgentConfig:
        content = Path(agent_md_path).read_text(encoding="utf-8")
        match = FRONTMATTER_PATTERN.match(content)
        if match is None:
            raise ValueError("Agent config must include YAML frontmatter.")

        frontmatter_raw, body = match.groups()
        frontmatter = cast(dict[str, Any], yaml.safe_load(frontmatter_raw) or {})
        frontmatter["system_prompt"] = body.strip()
        return AgentConfig.model_validate(frontmatter)


class AgentManager:
    def __init__(
        self,
        *,
        repository: RuntimeRepository,
        checkpointer: RuntimeCheckpointer,
        redis_client: Redis | None = None,
        runtime_settings: Settings = settings,
    ) -> None:
        self._repository = repository
        self._checkpointer = checkpointer
        self._settings = runtime_settings
        self._graphs: dict[str, CompiledStateGraph[Any, Any, Any, Any]] = {}
        self._configs: dict[str, AgentConfig] = {}

        memory_adapter: ShortTermMemoryAdapter
        if redis_client is None:
            memory_adapter = InMemoryShortTermMemoryAdapter()
        else:
            memory_adapter = RedisShortTermMemoryAdapter(redis_client)

        self._services = RuntimeNodeServices(
            memory=memory_adapter,
            model=MockModelAdapter(default_model=runtime_settings.default_primary_model),
            tools=MockToolExecutor(),
            repository=repository,
        )

    @classmethod
    def from_resources(
        cls,
        *,
        db_engine: AsyncEngine,
        redis_client: Redis,
        checkpointer: RuntimeCheckpointer,
        runtime_settings: Settings = settings,
    ) -> "AgentManager":
        return cls(
            repository=SqlRuntimeRepository(db_engine),
            checkpointer=checkpointer,
            redis_client=redis_client,
            runtime_settings=runtime_settings,
        )

    @classmethod
    def for_tests(
        cls,
        *,
        repository: RuntimeRepository | None = None,
        checkpointer: RuntimeCheckpointer | None = None,
    ) -> "AgentManager":
        return cls(
            repository=repository or InMemoryRuntimeRepository(),
            checkpointer=checkpointer or RuntimeCheckpointer(in_memory=True),
            redis_client=None,
            runtime_settings=settings,
        )

    async def create_agent(
        self,
        *,
        config_path: str | None = None,
        inline_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self._repository.ensure_schema()

        if config_path is not None:
            agent_config = AgentConfigParser.parse(config_path)
        elif inline_config is not None:
            agent_config = AgentConfig.model_validate(inline_config)
        else:
            raise ValueError("Either config_path or inline_config must be provided.")

        agent = await self._repository.create_agent(
            name=agent_config.name,
            version=agent_config.version,
            config=agent_config.model_dump(),
            status="created",
        )
        self._configs[agent.id] = agent_config
        return {"agent_id": agent.id, "status": agent.status}

    async def initialize_agent(self, agent_id: str) -> dict[str, Any]:
        await self._repository.ensure_schema()
        agent = await self._repository.get_agent(agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found.")

        agent_config = self._configs.get(agent_id)
        if agent_config is None:
            agent_config = AgentConfig.model_validate(agent.config)
            self._configs[agent_id] = agent_config

        self._graphs[agent_id] = build_agent_graph(
            agent_config.model_dump(),
            self._services,
            self._checkpointer,
        )
        await self._repository.update_agent_status(agent_id, "initialized")
        return {"agent_id": agent_id, "status": "initialized"}

    async def run_agent(
        self,
        agent_id: str,
        *,
        goal: str,
        thread_id: str,
        stop_after_steps: int | None = None,
    ) -> dict[str, Any]:
        if agent_id not in self._graphs:
            await self.initialize_agent(agent_id)

        agent = await self._repository.get_agent(agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found.")

        task = await self._repository.get_resumable_task(agent_id, thread_id)
        if task is None:
            task = await self._repository.create_task(
                agent_id=agent_id,
                goal=goal,
                thread_id=thread_id,
                status="running",
            )
        elif task.goal != goal:
            raise ValueError(
                f"Thread {thread_id} already has resumable task {task.id} "
                f"with goal '{task.goal}'. Use resume or a new thread_id."
            )

        await self._repository.update_agent_status(agent_id, "running")
        await self._repository.update_task_status(
            task.id,
            status="running",
            current_step=task.current_step,
        )

        state = await self._run_loop(
            agent_id=agent_id,
            goal=task.goal,
            thread_id=thread_id,
            task_id=task.id,
            stop_after_steps=stop_after_steps,
            resume=False,
        )
        return await self._finalize_result(agent_id, task.id, state)

    async def pause_agent(self, agent_id: str) -> dict[str, Any]:
        await self._repository.update_agent_status(agent_id, "paused")
        return {"agent_id": agent_id, "status": "paused"}

    async def resume_agent(
        self,
        agent_id: str,
        *,
        thread_id: str,
        stop_after_steps: int | None = None,
    ) -> dict[str, Any]:
        if agent_id not in self._graphs:
            await self.initialize_agent(agent_id)

        task = await self._repository.get_resumable_task(agent_id, thread_id)
        if task is None:
            latest_task = await self._repository.get_task_by_thread(agent_id, thread_id)
            if latest_task is None:
                raise ValueError(f"No task found for agent {agent_id} and thread {thread_id}.")
            message = (
                f"Task {latest_task.id} cannot be resumed because "
                f"it is in status '{latest_task.status}'."
            )
            raise ValueError(
                message
            )

        await self._repository.update_agent_status(agent_id, "running")
        await self._repository.update_task_status(
            task.id,
            status="running",
            current_step=task.current_step,
        )

        state = await self._run_loop(
            agent_id=agent_id,
            goal=task.goal,
            thread_id=thread_id,
            task_id=task.id,
            stop_after_steps=stop_after_steps,
            resume=True,
        )
        return await self._finalize_result(agent_id, task.id, state)

    async def get_agent_status(self, agent_id: str) -> dict[str, Any]:
        agent = await self._repository.get_agent(agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found.")

        latest_task = await self._repository.get_latest_task(agent_id)
        latest_step = None
        if latest_task is not None:
            latest_step = await self._repository.get_latest_task_step(latest_task.id)

        return {
            "agent_id": agent.id,
            "status": agent.status,
            "latest_task": None
            if latest_task is None
            else {
                "task_id": latest_task.id,
                "goal": latest_task.goal,
                "thread_id": latest_task.thread_id,
                "status": latest_task.status,
                "current_step": latest_task.current_step,
            },
            "latest_step": None
            if latest_step is None
            else {
                "step_index": latest_step.step_index,
                "action_type": latest_step.action_type,
                "result": latest_step.result,
            },
        }

    async def get_task_trace(self, task_id: str) -> dict[str, Any]:
        trace = await self._repository.get_task_trace(task_id)
        if trace is None:
            raise ValueError(f"Task {task_id} not found.")

        return {
            "task": {
                "task_id": trace.task.id,
                "agent_id": trace.task.agent_id,
                "goal": trace.task.goal,
                "thread_id": trace.task.thread_id,
                "status": trace.task.status,
                "current_step": trace.task.current_step,
                "created_at": trace.task.created_at,
                "completed_at": trace.task.completed_at,
            },
            "steps": [
                {
                    "step_id": item.step.id,
                    "step_index": item.step.step_index,
                    "action_type": item.step.action_type,
                    "plan": item.step.plan,
                    "result": item.step.result,
                    "model_used": item.step.model_used,
                    "created_at": item.step.created_at,
                    "tool_logs": [
                        {
                            "tool_log_id": log.id,
                            "tool_name": log.tool_name,
                            "input_params": log.input_params,
                            "output_result": log.output_result,
                            "latency_ms": log.latency_ms,
                            "success": log.success,
                            "error_message": log.error_message,
                            "created_at": log.created_at,
                        }
                        for log in item.tool_logs
                    ],
                }
                for item in trace.steps
            ],
        }

    async def _run_loop(
        self,
        *,
        agent_id: str,
        goal: str,
        thread_id: str,
        task_id: str,
        stop_after_steps: int | None,
        resume: bool,
    ) -> AgentState:
        graph = self._graphs[agent_id]
        agent_config = self._configs[agent_id]
        config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
        state: AgentState

        initial_state: AgentState = {
            "messages": [HumanMessage(content=goal)],
            "goal": goal,
            "tool_calls": [],
            "tool_results": [],
            "step_count": 0,
            "reflection": "",
            "status": "running",
            "agent_config": agent_config.model_dump(),
            "memory_context": "",
            "agent_id": agent_id,
            "task_id": task_id,
            "thread_id": thread_id,
            "last_action": "tool_call",
            "last_plan": {},
            "model_used": self._settings.default_primary_model,
        }

        next_input: AgentState | None = None if resume else initial_state
        while True:
            state = cast(AgentState, await graph.ainvoke(cast(Any, next_input), config=config))
            await self._repository.update_task_status(
                task_id,
                status=state["status"] if state["status"] != "running" else "running",
                current_step=state["step_count"],
                completed=state["status"] in {"completed", "failed", "escalate"},
            )

            if (
                stop_after_steps is not None
                and state["step_count"] >= stop_after_steps
                and state["status"] == "running"
            ):
                await self._repository.update_agent_status(agent_id, "paused")
                await self._repository.update_task_status(
                    task_id,
                    status="paused",
                    current_step=state["step_count"],
                )
                state["status"] = "paused"
                state["reflection"] = f"Paused after {state['step_count']} steps."
                return state

            if state["status"] in {"completed", "failed", "escalate"}:
                return state

            next_input = None

    async def _finalize_result(
        self,
        agent_id: str,
        task_id: str,
        state: AgentState,
    ) -> dict[str, Any]:
        final_status = state["status"]
        await self._repository.update_agent_status(agent_id, final_status)
        if final_status in {"completed", "failed", "escalate"}:
            await self._repository.update_task_status(
                task_id,
                status=final_status,
                current_step=state["step_count"],
                completed=True,
            )
        elif final_status == "paused":
            await self._repository.update_task_status(
                task_id,
                status="paused",
                current_step=state["step_count"],
            )

        return {
            "agent_id": agent_id,
            "task_id": task_id,
            "status": final_status,
            "step_count": state["step_count"],
            "reflection": state["reflection"],
            "messages": [
                {"type": item["type"], "content": item["data"]["content"]}
                for item in messages_to_dict(state["messages"])
            ],
        }
