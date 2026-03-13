from typing import Any, Generic, TypeVar

from pydantic import BaseModel

DataT = TypeVar("DataT")


class SuccessResponse(BaseModel, Generic[DataT]):
    status: str = "success"
    data: DataT


class ErrorResponse(BaseModel):
    status: str = "error"
    code: str
    message: str
    details: Any | None = None


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
