from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

DataT = TypeVar("DataT")


class SuccessResponse(BaseModel, Generic[DataT]):
    code: int = 1
    data: DataT


class ErrorResponse(BaseModel):
    code: int = 0
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str
    db: bool
    redis: bool


class CreateAgentRequest(BaseModel):
    agent_config_path: str | None = None
    inline_config: dict[str, Any] | None = None


class AgentRunRequest(BaseModel):
    goal: str
    thread_id: str


class AgentResumeRequest(BaseModel):
    thread_id: str


class AgentSummaryResponse(BaseModel):
    agent_id: str
    status: str


class AgentMessageResponse(BaseModel):
    type: str
    content: Any


class AgentRunResponse(BaseModel):
    agent_id: str
    task_id: str
    status: str
    step_count: int
    reflection: str
    messages: list[AgentMessageResponse]


class AgentTaskSummaryResponse(BaseModel):
    task_id: str
    goal: str
    thread_id: str
    status: str
    current_step: int


class AgentStepSummaryResponse(BaseModel):
    step_index: int
    action_type: str
    result: dict[str, Any]


class AgentStatusResponse(BaseModel):
    agent_id: str
    status: str
    latest_task: AgentTaskSummaryResponse | None = None
    latest_step: AgentStepSummaryResponse | None = None


class TaskTraceToolLogResponse(BaseModel):
    tool_log_id: str
    tool_name: str
    input_params: dict[str, Any]
    output_result: dict[str, Any]
    latency_ms: int
    success: bool
    error_message: str | None = None
    created_at: datetime


class TaskTraceStepResponse(BaseModel):
    step_id: str
    step_index: int
    action_type: str
    plan: dict[str, Any]
    result: dict[str, Any]
    model_used: str
    created_at: datetime
    tool_logs: list[TaskTraceToolLogResponse]


class TaskTraceTaskResponse(BaseModel):
    task_id: str
    agent_id: str
    goal: str
    thread_id: str
    status: str
    current_step: int
    created_at: datetime
    completed_at: datetime | None = None


class TaskTraceResponse(BaseModel):
    task: TaskTraceTaskResponse
    steps: list[TaskTraceStepResponse]
