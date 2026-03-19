# ruff: noqa: E501

from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AgentRecord:
    id: str
    name: str
    version: str
    config: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime


@dataclass
class TaskRecord:
    id: str
    agent_id: str
    goal: str
    thread_id: str
    status: str
    current_step: int
    dag: dict[str, Any]
    created_at: datetime
    completed_at: datetime | None = None


@dataclass
class TaskStepRecord:
    id: str
    task_id: str
    step_index: int
    action_type: str
    plan: dict[str, Any]
    result: dict[str, Any]
    model_used: str
    token_usage: dict[str, Any]
    trace_meta: dict[str, Any]
    created_at: datetime


@dataclass
class ToolLogRecord:
    id: str
    task_step_id: str
    tool_name: str
    input_params: dict[str, Any]
    output_result: dict[str, Any]
    latency_ms: int
    success: bool
    error_message: str | None
    created_at: datetime


@dataclass
class TaskTraceStep:
    step: TaskStepRecord
    tool_logs: list[ToolLogRecord]


@dataclass
class TaskTraceRecord:
    task: TaskRecord
    steps: list[TaskTraceStep]


def _to_agent_record(row: Any) -> AgentRecord:
    return AgentRecord(
        id=str(row["id"]),
        name=str(row["name"]),
        version=str(row["version"]),
        config=dict(row["config"]),
        status=str(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_task_record(row: Any) -> TaskRecord:
    return TaskRecord(
        id=str(row["id"]),
        agent_id=str(row["agent_id"]),
        goal=str(row["goal"]),
        thread_id=str(row["thread_id"]),
        status=str(row["status"]),
        current_step=int(row["current_step"]),
        dag=dict(row["dag"]),
        created_at=row["created_at"],
        completed_at=row["completed_at"],
    )


def _to_task_step_record(row: Any) -> TaskStepRecord:
    return TaskStepRecord(
        id=str(row["id"]),
        task_id=str(row["task_id"]),
        step_index=int(row["step_index"]),
        action_type=str(row["action_type"]),
        plan=dict(row["plan"]),
        result=dict(row["result"]),
        model_used=str(row["model_used"]),
        token_usage=dict(row["token_usage"] or {}),
        trace_meta=dict(row["trace_meta"] or {}),
        created_at=row["created_at"],
    )


def _to_tool_log_record(row: Any) -> ToolLogRecord:
    return ToolLogRecord(
        id=str(row["id"]),
        task_step_id=str(row["task_step_id"]),
        tool_name=str(row["tool_name"]),
        input_params=dict(row["input_params"]),
        output_result=dict(row["output_result"]),
        latency_ms=int(row["latency_ms"]),
        success=bool(row["success"]),
        error_message=row["error_message"],
        created_at=row["created_at"],
    )


def _ensure_updated(rowcount: int | None, *, entity_name: str, entity_id: str) -> None:
    if rowcount == 0:
        raise ValueError(f"{entity_name} {entity_id} not found.")


class RuntimeRepository(ABC):

    @abstractmethod
    async def create_agent(
        self,
        *,
        name: str,
        version: str,
        config: dict[str, Any],
        status: str,
    ) -> AgentRecord:
        raise NotImplementedError

    @abstractmethod
    async def update_agent_status(self, agent_id: str, status: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_agent(self, agent_id: str) -> AgentRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def get_agent_by_name(self, name: str) -> AgentRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def create_task(self, *, agent_id: str, goal: str, thread_id: str, status: str) -> TaskRecord:
        raise NotImplementedError

    @abstractmethod
    async def request_task_pause(self, task_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def update_task_progress(self, task_id: str, *, current_step: int) -> None:
        raise NotImplementedError

    @abstractmethod
    async def update_task_status(
        self,
        task_id: str,
        *,
        status: str,
        current_step: int,
        completed: bool = False,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    async def get_task(self, task_id: str) -> TaskRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def get_task_by_thread(self, agent_id: str, thread_id: str) -> TaskRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def get_agent_active_task(self, agent_id: str) -> TaskRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def list_tasks_by_status(self, statuses: set[str]) -> list[TaskRecord]:
        raise NotImplementedError

    @abstractmethod
    async def get_latest_task(self, agent_id: str) -> TaskRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def create_task_step(
        self,
        *,
        task_id: str,
        step_index: int,
        action_type: str,
        plan: dict[str, Any],
        result: dict[str, Any],
        model_used: str,
        token_usage: dict[str, Any] | None = None,
        trace_meta: dict[str, Any] | None = None,
    ) -> TaskStepRecord:
        raise NotImplementedError

    @abstractmethod
    async def get_latest_task_step(self, task_id: str) -> TaskStepRecord | None:
        raise NotImplementedError

    @abstractmethod
    async def create_tool_log(
        self,
        *,
        task_step_id: str,
        tool_name: str,
        input_params: dict[str, Any],
        output_result: dict[str, Any],
        latency_ms: int,
        success: bool,
        error_message: str | None,
    ) -> ToolLogRecord:
        raise NotImplementedError

    @abstractmethod
    async def list_tool_logs(self, task_id: str) -> list[ToolLogRecord]:
        raise NotImplementedError

    @abstractmethod
    async def get_task_trace(self, task_id: str) -> TaskTraceRecord | None:
        raise NotImplementedError


class SqlRuntimeRepository(RuntimeRepository):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create_agent(
        self,
        *,
        name: str,
        version: str,
        config: dict[str, Any],
        status: str,
    ) -> AgentRecord:
        agent_id = str(uuid.uuid4())
        now = utcnow()
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO agents (id, name, version, config, status, created_at, updated_at)
                    VALUES (:id, :name, :version, CAST(:config AS JSONB), :status, :created_at, :updated_at)
                    """
                ),
                {
                    "id": agent_id,
                    "name": name,
                    "version": version,
                    "config": json.dumps(config),
                    "status": status,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        return AgentRecord(agent_id, name, version, config, status, now, now)

    async def update_agent_status(self, agent_id: str, status: str) -> None:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                text("UPDATE agents SET status = :status, updated_at = CURRENT_TIMESTAMP WHERE id = :id"),
                {"id": agent_id, "status": status},
            )
        _ensure_updated(result.rowcount, entity_name="Agent", entity_id=agent_id)

    async def get_agent(self, agent_id: str) -> AgentRecord | None:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id, name, version, config, status, created_at, updated_at
                    FROM agents
                    WHERE id = :id
                    """
                ),
                {"id": agent_id},
            )
            row = result.mappings().first()
        return _to_agent_record(row) if row is not None else None

    async def get_agent_by_name(self, name: str) -> AgentRecord | None:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id, name, version, config, status, created_at, updated_at
                    FROM agents
                    WHERE name = :name
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"name": name},
            )
            row = result.mappings().first()
        return _to_agent_record(row) if row is not None else None

    async def create_task(self, *, agent_id: str, goal: str, thread_id: str, status: str) -> TaskRecord:
        task_id = str(uuid.uuid4())
        now = utcnow()
        dag = {
            "thread_id": thread_id,
        }
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO tasks (id, agent_id, goal, thread_id, status, dag, current_step, created_at)
                    VALUES (:id, :agent_id, :goal, :thread_id, :status, CAST(:dag AS JSONB), :current_step, :created_at)
                    """
                ),
                {
                    "id": task_id,
                    "agent_id": agent_id,
                    "goal": goal,
                    "thread_id": thread_id,
                    "status": status,
                    "dag": json.dumps(dag),
                    "current_step": 0,
                    "created_at": now,
                },
            )
        return TaskRecord(task_id, agent_id, goal, thread_id, status, 0, dag, now)

    async def request_task_pause(self, task_id: str) -> bool:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                text(
                    """
                    UPDATE tasks
                    SET status = 'pausing'
                    WHERE id = :id
                      AND status = 'running'
                    """
                ),
                {"id": task_id},
            )
        return bool(result.rowcount)

    async def update_task_progress(self, task_id: str, *, current_step: int) -> None:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                text(
                    """
                    UPDATE tasks
                    SET current_step = :current_step
                    WHERE id = :id
                    """
                ),
                {
                    "id": task_id,
                    "current_step": current_step,
                },
            )
        _ensure_updated(result.rowcount, entity_name="Task", entity_id=task_id)

    async def update_task_status(
        self,
        task_id: str,
        *,
        status: str,
        current_step: int,
        completed: bool = False,
    ) -> None:
        async with self._engine.begin() as connection:
            result = await connection.execute(
                text(
                    """
                    UPDATE tasks
                    SET status = :status,
                        current_step = :current_step,
                        completed_at = CASE WHEN :completed THEN CURRENT_TIMESTAMP ELSE completed_at END
                    WHERE id = :id
                    """
                ),
                {
                    "id": task_id,
                    "status": status,
                    "current_step": current_step,
                    "completed": completed,
                },
            )
        _ensure_updated(result.rowcount, entity_name="Task", entity_id=task_id)

    async def get_task(self, task_id: str) -> TaskRecord | None:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id, agent_id, goal, thread_id, status, dag, current_step, created_at, completed_at
                    FROM tasks
                    WHERE id = :id
                    """
                ),
                {"id": task_id},
            )
            row = result.mappings().first()
        return _to_task_record(row) if row is not None else None

    async def get_task_by_thread(self, agent_id: str, thread_id: str) -> TaskRecord | None:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id, agent_id, goal, thread_id, status, dag, current_step, created_at, completed_at
                    FROM tasks
                    WHERE agent_id = :agent_id AND thread_id = :thread_id
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"agent_id": agent_id, "thread_id": thread_id},
            )
            row = result.mappings().first()
        return _to_task_record(row) if row is not None else None

    async def get_agent_active_task(self, agent_id: str) -> TaskRecord | None:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id, agent_id, goal, thread_id, status, dag, current_step, created_at, completed_at
                    FROM tasks
                    WHERE agent_id = :agent_id
                      AND status IN ('running', 'pausing', 'paused')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"agent_id": agent_id},
            )
            row = result.mappings().first()
        return _to_task_record(row) if row is not None else None

    async def list_tasks_by_status(self, statuses: set[str]) -> list[TaskRecord]:
        if not statuses:
            return []
        placeholders = ", ".join(f":status_{idx}" for idx, _ in enumerate(statuses))
        params = {f"status_{idx}": status for idx, status in enumerate(statuses)}
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text(
                    f"""
                    SELECT id, agent_id, goal, thread_id, status, dag, current_step, created_at, completed_at
                    FROM tasks
                    WHERE status IN ({placeholders})
                    ORDER BY created_at ASC
                    """
                ),
                params,
            )
            rows = result.mappings().all()
        return [_to_task_record(row) for row in rows]

    async def get_latest_task(self, agent_id: str) -> TaskRecord | None:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id, agent_id, goal, thread_id, status, dag, current_step, created_at, completed_at
                    FROM tasks
                    WHERE agent_id = :agent_id
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"agent_id": agent_id},
            )
            row = result.mappings().first()
        return _to_task_record(row) if row is not None else None

    async def create_task_step(
        self,
        *,
        task_id: str,
        step_index: int,
        action_type: str,
        plan: dict[str, Any],
        result: dict[str, Any],
        model_used: str,
        token_usage: dict[str, Any] | None = None,
        trace_meta: dict[str, Any] | None = None,
    ) -> TaskStepRecord:
        step_id = str(uuid.uuid4())
        now = utcnow()
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO task_steps (
                        id, task_id, step_index, action_type, plan, result, latency_ms, model_used, token_usage, trace_meta, created_at
                    )
                    VALUES (
                        :id, :task_id, :step_index, :action_type,
                        CAST(:plan AS JSONB), CAST(:result AS JSONB), 0, :model_used, CAST(:token_usage AS JSONB), CAST(:trace_meta AS JSONB), :created_at
                    )
                    """
                ),
                {
                    "id": step_id,
                    "task_id": task_id,
                    "step_index": step_index,
                    "action_type": action_type,
                    "plan": json.dumps(plan),
                    "result": json.dumps(result),
                    "model_used": model_used,
                    "token_usage": json.dumps(token_usage or {}),
                    "trace_meta": json.dumps(trace_meta or {}),
                    "created_at": now,
                },
            )
        return TaskStepRecord(
            step_id,
            task_id,
            step_index,
            action_type,
            plan,
            result,
            model_used,
            token_usage or {},
            trace_meta or {},
            now,
        )

    async def get_latest_task_step(self, task_id: str) -> TaskStepRecord | None:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT id, task_id, step_index, action_type, plan, result, model_used, token_usage, trace_meta, created_at
                    FROM task_steps
                    WHERE task_id = :task_id
                    ORDER BY step_index DESC, created_at DESC
                    LIMIT 1
                    """
                ),
                {"task_id": task_id},
            )
            row = result.mappings().first()
        return _to_task_step_record(row) if row is not None else None

    async def create_tool_log(
        self,
        *,
        task_step_id: str,
        tool_name: str,
        input_params: dict[str, Any],
        output_result: dict[str, Any],
        latency_ms: int,
        success: bool,
        error_message: str | None,
    ) -> ToolLogRecord:
        log_id = str(uuid.uuid4())
        now = utcnow()
        async with self._engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO tool_logs (
                        id, task_step_id, tool_name, input_params, output_result,
                        sandbox_type, permissions_used, latency_ms, success, error_message, created_at
                    )
                    VALUES (
                        :id, :task_step_id, :tool_name, CAST(:input_params AS JSONB), CAST(:output_result AS JSONB),
                        :sandbox_type, :permissions_used, :latency_ms, :success, :error_message, :created_at
                    )
                    """
                ),
                {
                    "id": log_id,
                    "task_step_id": task_step_id,
                    "tool_name": tool_name,
                    "input_params": json.dumps(input_params),
                    "output_result": json.dumps(output_result),
                    "sandbox_type": "mock",
                    "permissions_used": [],
                    "latency_ms": latency_ms,
                    "success": success,
                    "error_message": error_message,
                    "created_at": now,
                },
            )
        return ToolLogRecord(log_id, task_step_id, tool_name, input_params, output_result, latency_ms, success, error_message, now)

    async def list_tool_logs(self, task_id: str) -> list[ToolLogRecord]:
        async with self._engine.connect() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT tl.id, tl.task_step_id, tl.tool_name, tl.input_params, tl.output_result,
                           tl.latency_ms, tl.success, tl.error_message, tl.created_at
                    FROM tool_logs tl
                    INNER JOIN task_steps ts ON ts.id = tl.task_step_id
                    WHERE ts.task_id = :task_id
                    ORDER BY tl.created_at ASC
                    """
                ),
                {"task_id": task_id},
            )
            rows = result.mappings().all()
        return [_to_tool_log_record(row) for row in rows]

    async def get_task_trace(self, task_id: str) -> TaskTraceRecord | None:
        task = await self.get_task(task_id)
        if task is None:
            return None

        async with self._engine.connect() as connection:
            step_result = await connection.execute(
                text(
                    """
                    SELECT id, task_id, step_index, action_type, plan, result, model_used, token_usage, trace_meta, created_at
                    FROM task_steps
                    WHERE task_id = :task_id
                    ORDER BY step_index ASC, created_at ASC
                    """
                ),
                {"task_id": task_id},
            )
            step_rows = step_result.mappings().all()

            log_result = await connection.execute(
                text(
                    """
                    SELECT tl.id, tl.task_step_id, tl.tool_name, tl.input_params, tl.output_result,
                           tl.latency_ms, tl.success, tl.error_message, tl.created_at
                    FROM tool_logs tl
                    INNER JOIN task_steps ts ON ts.id = tl.task_step_id
                    WHERE ts.task_id = :task_id
                    ORDER BY ts.step_index ASC, tl.created_at ASC
                    """
                ),
                {"task_id": task_id},
            )
            log_rows = log_result.mappings().all()

        logs_by_step: dict[str, list[ToolLogRecord]] = defaultdict(list)
        for row in log_rows:
            step_id = str(row["task_step_id"])
            logs_by_step[step_id].append(_to_tool_log_record(row))

        steps: list[TaskTraceStep] = []
        for row in step_rows:
            step = _to_task_step_record(row)
            steps.append(TaskTraceStep(step=step, tool_logs=logs_by_step.get(step.id, [])))

        return TaskTraceRecord(task=task, steps=steps)


class InMemoryRuntimeRepository(RuntimeRepository):
    def __init__(self) -> None:
        self.agents: dict[str, AgentRecord] = {}
        self.tasks: dict[str, TaskRecord] = {}
        self.task_steps: dict[str, list[TaskStepRecord]] = defaultdict(list)
        self.tool_logs: dict[str, list[ToolLogRecord]] = defaultdict(list)
        self._step_task_index: dict[str, str] = {}

    async def create_agent(
        self,
        *,
        name: str,
        version: str,
        config: dict[str, Any],
        status: str,
    ) -> AgentRecord:
        agent = AgentRecord(str(uuid.uuid4()), name, version, config, status, utcnow(), utcnow())
        self.agents[agent.id] = agent
        return agent

    async def update_agent_status(self, agent_id: str, status: str) -> None:
        agent = self.agents.get(agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found.")
        agent.status = status
        agent.updated_at = utcnow()

    async def get_agent(self, agent_id: str) -> AgentRecord | None:
        return self.agents.get(agent_id)

    async def get_agent_by_name(self, name: str) -> AgentRecord | None:
        candidates = [agent for agent in self.agents.values() if agent.name == name]
        candidates.sort(key=lambda agent: agent.created_at, reverse=True)
        return candidates[0] if candidates else None

    async def create_task(self, *, agent_id: str, goal: str, thread_id: str, status: str) -> TaskRecord:
        task = TaskRecord(
            str(uuid.uuid4()),
            agent_id,
            goal,
            thread_id,
            status,
            0,
            {
                "thread_id": thread_id,
            },
            utcnow(),
        )
        self.tasks[task.id] = task
        return task

    async def request_task_pause(self, task_id: str) -> bool:
        task = self.tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found.")
        if task.status != "running":
            return False
        task.status = "pausing"
        return True

    async def update_task_progress(self, task_id: str, *, current_step: int) -> None:
        task = self.tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found.")
        task.current_step = current_step

    async def update_task_status(
        self,
        task_id: str,
        *,
        status: str,
        current_step: int,
        completed: bool = False,
    ) -> None:
        task = self.tasks.get(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found.")
        task.status = status
        task.current_step = current_step
        if completed:
            task.completed_at = utcnow()

    async def get_task(self, task_id: str) -> TaskRecord | None:
        return self.tasks.get(task_id)

    async def get_task_by_thread(self, agent_id: str, thread_id: str) -> TaskRecord | None:
        candidates = [task for task in self.tasks.values() if task.agent_id == agent_id and task.thread_id == thread_id]
        candidates.sort(key=lambda task: task.created_at, reverse=True)
        return candidates[0] if candidates else None

    async def get_agent_active_task(self, agent_id: str) -> TaskRecord | None:
        candidates = [
            task
            for task in self.tasks.values()
            if task.agent_id == agent_id and task.status in {"running", "pausing", "paused"}
        ]
        candidates.sort(key=lambda task: task.created_at, reverse=True)
        return candidates[0] if candidates else None

    async def list_tasks_by_status(self, statuses: set[str]) -> list[TaskRecord]:
        candidates = [task for task in self.tasks.values() if task.status in statuses]
        candidates.sort(key=lambda task: task.created_at)
        return candidates

    async def get_latest_task(self, agent_id: str) -> TaskRecord | None:
        candidates = [task for task in self.tasks.values() if task.agent_id == agent_id]
        candidates.sort(key=lambda task: task.created_at, reverse=True)
        return candidates[0] if candidates else None

    async def create_task_step(
        self,
        *,
        task_id: str,
        step_index: int,
        action_type: str,
        plan: dict[str, Any],
        result: dict[str, Any],
        model_used: str,
        token_usage: dict[str, Any] | None = None,
        trace_meta: dict[str, Any] | None = None,
    ) -> TaskStepRecord:
        step = TaskStepRecord(
            str(uuid.uuid4()),
            task_id,
            step_index,
            action_type,
            plan,
            result,
            model_used,
            token_usage or {},
            trace_meta or {},
            utcnow(),
        )
        self.task_steps[task_id].append(step)
        self._step_task_index[step.id] = task_id
        return step

    async def get_latest_task_step(self, task_id: str) -> TaskStepRecord | None:
        steps = self.task_steps.get(task_id, [])
        return steps[-1] if steps else None

    async def create_tool_log(
        self,
        *,
        task_step_id: str,
        tool_name: str,
        input_params: dict[str, Any],
        output_result: dict[str, Any],
        latency_ms: int,
        success: bool,
        error_message: str | None,
    ) -> ToolLogRecord:
        log = ToolLogRecord(
            str(uuid.uuid4()),
            task_step_id,
            tool_name,
            input_params,
            output_result,
            latency_ms,
            success,
            error_message,
            utcnow(),
        )
        task_id = self._step_task_index.get(task_step_id)
        if task_id is None:
            raise ValueError(f"Task step {task_step_id} not found.")
        self.tool_logs[task_id].append(log)
        return log

    async def list_tool_logs(self, task_id: str) -> list[ToolLogRecord]:
        return list(self.tool_logs.get(task_id, []))

    async def get_task_trace(self, task_id: str) -> TaskTraceRecord | None:
        task = self.tasks.get(task_id)
        if task is None:
            return None

        steps = sorted(
            self.task_steps.get(task_id, []),
            key=lambda item: (item.step_index, item.created_at),
        )
        trace_steps: list[TaskTraceStep] = []
        for step in steps:
            logs = [
                log
                for log in self.tool_logs.get(task_id, [])
                if log.task_step_id == step.id
            ]
            trace_steps.append(TaskTraceStep(step=step, tool_logs=logs))
        return TaskTraceRecord(task=task, steps=trace_steps)
