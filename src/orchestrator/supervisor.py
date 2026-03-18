from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import structlog

from src.orchestrator.registry import AgentRegistry, RoutingDecision
from src.runtime.lifecycle import AgentConfigParser, AgentManager
from src.runtime.repository import RuntimeRepository

logger = structlog.get_logger(__name__)
ENGINE_NAME = "internal_orchestrator"
ASCII_WORD_RE = re.compile(r"[a-z0-9_]+")
NON_WORD_RE = re.compile(r"[^a-z0-9_\u4e00-\u9fff]+")


@dataclass(frozen=True)
class DelegationTask:
    agent_name: str
    sub_goal: str


class IntentRouter:
    def route(self, goal: str, registry: AgentRegistry) -> RoutingDecision:
        text = self._normalize_text(goal)
        scored = self._score_intents(text=text, registry=registry)

        if not scored:
            return registry.resolve("default_*")

        matched_intents = self._matched_intents(scored)
        selected_agents, mode = self._merge_decisions(
            decisions=[registry.resolve(intent) for intent in matched_intents]
        )

        if not selected_agents:
            return registry.resolve("default_*")

        merged_intent = ",".join(sorted(matched_intents))
        return RoutingDecision(intent=merged_intent, selected_agents=selected_agents, mode=mode)

    def _score_intents(self, *, text: str, registry: AgentRegistry) -> list[tuple[str, int]]:
        scored: list[tuple[str, int]] = []
        for rule in registry.list_routing_rules():
            if not rule.keywords:
                continue
            score = sum(1 for keyword in rule.keywords if self._matches_keyword(text, keyword))
            if score > 0:
                scored.append((rule.intent, score))
        return scored

    def _matched_intents(self, scored: list[tuple[str, int]]) -> set[str]:
        max_score = max(score for _, score in scored)
        return {intent for intent, score in scored if score == max_score}

    def _merge_decisions(self, *, decisions: list[RoutingDecision]) -> tuple[list[str], str]:
        selected_agents: list[str] = []
        mode = "single"
        for decision in decisions:
            if decision.mode == "multi_agent_consultation":
                mode = decision.mode
            for agent in decision.selected_agents:
                if agent not in selected_agents:
                    selected_agents.append(agent)
        if len(selected_agents) > 1:
            mode = "multi_agent_consultation"
        return selected_agents, mode

    def _normalize_text(self, text: str) -> str:
        normalized = NON_WORD_RE.sub(" ", text.lower())
        return " ".join(normalized.split())

    def _matches_keyword(self, text: str, keyword: str) -> bool:
        normalized_keyword = self._normalize_text(keyword)
        if not normalized_keyword:
            return False
        if ASCII_WORD_RE.fullmatch(normalized_keyword):
            return normalized_keyword in text.split()
        return normalized_keyword in text


class SupervisorOrchestrator:
    def __init__(
        self,
        *,
        registry: AgentRegistry,
        agent_manager: AgentManager,
        repository: RuntimeRepository,
        intent_router: IntentRouter | None = None,
        max_parallel_workers: int = 3,
    ) -> None:
        self._registry = registry
        self._agent_manager = agent_manager
        self._repository = repository
        self._intent_router = intent_router or IntentRouter()
        self._max_parallel_workers = max(1, max_parallel_workers)
        self._graph_info = self.build_supervisor_graph()

    async def list_agents(self) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for item in self._registry.list_agents():
            output.append(
                {
                    "name": item.name,
                    "type": item.type,
                    "description": item.description,
                    "capabilities": item.capabilities,
                    "tools": item.tools,
                }
            )
        return output

    async def run(self, *, goal: str, thread_id: str) -> dict[str, Any]:
        supervisor_id = await self._create_supervisor_agent()
        task = await self._repository.create_task(
            agent_id=supervisor_id,
            goal=goal,
            thread_id=thread_id,
            status="running",
        )
        await self._repository.update_agent_status(supervisor_id, "running")
        current_step = 0
        try:
            decision = self._intent_router.route(goal, self._registry)
            delegation_tasks = self._build_delegation_tasks(goal, decision)
            supervisor_step = await self._repository.create_task_step(
                task_id=task.id,
                step_index=1,
                action_type="plan",
                plan={
                    "decision": "delegate",
                    "intent": decision.intent,
                    "mode": decision.mode,
                    "engine": str(self._graph_info.get("engine", ENGINE_NAME)),
                    "delegation_tasks": [item.__dict__ for item in delegation_tasks],
                },
                result={"status": "delegating"},
                model_used=ENGINE_NAME,
                trace_meta={
                    "node_role": "supervisor",
                    "orchestrator_task_id": task.id,
                },
            )
            current_step = 1

            sub_results = await self._run_delegations(
                orchestration_task_id=task.id,
                parent_step_id=supervisor_step.id,
                thread_id=thread_id,
                tasks=delegation_tasks,
                base_step_index=2,
            )

            success_count = sum(1 for item in sub_results if item["status"] == "completed")
            final_status = "completed" if success_count == len(sub_results) else "failed"
            final_step_index = 2 + len(delegation_tasks)
            await self._repository.create_task_step(
                task_id=task.id,
                step_index=final_step_index,
                action_type="respond",
                plan={"decision": "aggregate"},
                result={
                    "status": final_status,
                    "summary": self._build_summary(goal, sub_results),
                    "results": sub_results,
                },
                model_used=ENGINE_NAME,
                trace_meta={
                    "node_role": "supervisor",
                    "parent_step_id": supervisor_step.id,
                    "orchestrator_task_id": task.id,
                },
            )
            await self._repository.update_task_status(
                task.id,
                status=final_status,
                current_step=final_step_index,
                completed=True,
            )
            await self._repository.update_agent_status(supervisor_id, final_status)
            return {
                "task_id": task.id,
                "thread_id": thread_id,
                "status": final_status,
                "intent": decision.intent,
                "mode": decision.mode,
                "delegations": sub_results,
                "summary": self._build_summary(goal, sub_results),
            }
        except Exception as exc:
            failure_step_index = current_step + 1
            try:
                await self._repository.create_task_step(
                    task_id=task.id,
                    step_index=failure_step_index,
                    action_type="error",
                    plan={"decision": "abort"},
                    result={
                        "status": "failed",
                        "error": {
                            "code": "orchestrator_run_error",
                            "type": exc.__class__.__name__,
                            "message": str(exc),
                        },
                    },
                    model_used=ENGINE_NAME,
                    trace_meta={
                        "node_role": "supervisor",
                        "orchestrator_task_id": task.id,
                    },
                )
            finally:
                await self._repository.update_task_status(
                    task.id,
                    status="failed",
                    current_step=failure_step_index,
                    completed=True,
                )
                await self._repository.update_agent_status(supervisor_id, "failed")
            raise

    def build_supervisor_graph(self) -> dict[str, Any]:
        members = [
            item.name for item in self._registry.list_agents() if item.type != "orchestrator"
        ]
        prompt = (
            "你是任务协调器，根据用户需求把任务分发给专家 Agent。\n"
            f"可用专家:\n{self._registry.as_prompt_context()}"
        )
        return {
            "engine": ENGINE_NAME,
            "members": members,
            "prompt": prompt,
        }

    async def _create_supervisor_agent(self) -> str:
        created = await self._repository.create_agent(
            name="orchestrator-supervisor",
            version="0.1.0",
            config={"type": "orchestrator"},
            status="initialized",
        )
        return created.id

    def _build_delegation_tasks(
        self,
        goal: str,
        decision: RoutingDecision,
    ) -> list[DelegationTask]:
        selected = decision.selected_agents
        if not selected:
            selected = self._registry.list_domain_agent_names()[:1]
        return [DelegationTask(agent_name=name, sub_goal=goal) for name in selected]

    async def _run_delegations(
        self,
        *,
        orchestration_task_id: str,
        parent_step_id: str,
        thread_id: str,
        tasks: list[DelegationTask],
        base_step_index: int,
    ) -> list[dict[str, Any]]:
        if not tasks:
            return []
        if len(tasks) <= 1:
            single = await self._run_one_delegation(
                orchestration_task_id=orchestration_task_id,
                parent_step_id=parent_step_id,
                thread_id=thread_id,
                task=tasks[0],
                step_index=base_step_index,
            )
            return [single]

        semaphore = asyncio.Semaphore(self._max_parallel_workers)

        async def runner(step_index: int, task: DelegationTask) -> dict[str, Any]:
            async with semaphore:
                return await self._run_one_delegation(
                    orchestration_task_id=orchestration_task_id,
                    parent_step_id=parent_step_id,
                    thread_id=thread_id,
                    task=task,
                    step_index=step_index,
                )

        return list(
            await asyncio.gather(
                *(runner(base_step_index + idx, item) for idx, item in enumerate(tasks))
            )
        )

    async def _run_one_delegation(
        self,
        *,
        orchestration_task_id: str,
        parent_step_id: str,
        thread_id: str,
        task: DelegationTask,
        step_index: int,
    ) -> dict[str, Any]:
        worker_agent_id = ""
        error_payload: dict[str, Any] | None = None

        try:
            worker_agent_id = await self._create_worker_agent(task.agent_name)
            worker_thread = f"{thread_id}:{orchestration_task_id}:{task.agent_name}"
            run_result = await self._agent_manager.run_agent(
                worker_agent_id,
                goal=task.sub_goal,
                thread_id=worker_thread,
            )
            status = str(run_result.get("status", "failed"))
        except Exception as exc:
            logger.exception("Worker delegation failed", worker=task.agent_name, exc_info=exc)
            run_result = {
                "agent_id": worker_agent_id,
                "task_id": "",
                "status": "failed",
                "reflection": str(exc),
                "messages": [],
                "step_count": 0,
            }
            status = "failed"
            error_payload = {
                "code": "worker_run_error",
                "type": exc.__class__.__name__,
                "message": str(exc),
            }

        await self._repository.create_task_step(
            task_id=orchestration_task_id,
            step_index=step_index,
            action_type="delegate",
            plan={
                "agent_name": task.agent_name,
                "sub_goal": task.sub_goal,
            },
            result={
                "worker_agent_id": worker_agent_id,
                "worker_task_id": run_result.get("task_id", ""),
                "status": status,
                "reflection": run_result.get("reflection", ""),
                "step_count": run_result.get("step_count", 0),
                "error": error_payload,
            },
            model_used=ENGINE_NAME,
            trace_meta={
                "node_role": "worker",
                "worker_agent": task.agent_name,
                "parent_step_id": parent_step_id,
                "orchestrator_task_id": orchestration_task_id,
            },
        )
        return {
            "worker": task.agent_name,
            "worker_agent_id": worker_agent_id,
            "worker_task_id": run_result.get("task_id", ""),
            "status": status,
            "reflection": run_result.get("reflection", ""),
            "step_count": run_result.get("step_count", 0),
            "error": error_payload,
        }

    async def _create_worker_agent(self, worker_name: str) -> str:
        entry = self._registry.get_agent(worker_name)
        if entry is None or not entry.config_path:
            raise ValueError(f"Worker agent '{worker_name}' config_path is not configured.")

        config_path = Path(entry.config_path)
        if not config_path.is_absolute():
            config_path = Path.cwd() / config_path
        _ = AgentConfigParser.parse(str(config_path))
        created = await self._agent_manager.create_agent(config_path=str(config_path))
        return str(created["agent_id"])

    def _build_summary(self, goal: str, sub_results: list[dict[str, Any]]) -> str:
        completed = [item["worker"] for item in sub_results if item["status"] == "completed"]
        failed = [item["worker"] for item in sub_results if item["status"] != "completed"]
        if failed:
            return (
                f"Goal: {goal}. Completed workers: {', '.join(completed) or '-'}; "
                f"Failed workers: {', '.join(failed)}."
            )
        return f"Goal: {goal}. All workers completed: {', '.join(completed) or '-'}."
