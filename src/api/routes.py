from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import get_agent_manager
from src.api.schemas import (
    AgentPauseRequest,
    AgentResumeRequest,
    AgentRunRequest,
    AgentRunResponse,
    AgentStatusResponse,
    AgentSummaryResponse,
    CreateAgentRequest,
    SuccessResponse,
    TaskTraceResponse,
)
from src.runtime.lifecycle import AgentManager

api_router = APIRouter()


@api_router.post("/agents", response_model=SuccessResponse[AgentSummaryResponse], tags=["agents"])
async def create_agent(
    request: CreateAgentRequest,
    manager: Annotated[AgentManager, Depends(get_agent_manager)],
) -> SuccessResponse[AgentSummaryResponse]:
    if request.agent_config_path is None and request.inline_config is None:
        raise HTTPException(
            status_code=400,
            detail="agent_config_path or inline_config is required",
        )
    try:
        result = await manager.create_agent(
            config_path=request.agent_config_path,
            inline_config=request.inline_config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SuccessResponse(data=AgentSummaryResponse(**result))


@api_router.post("/agents/run", response_model=SuccessResponse[AgentRunResponse], tags=["agents"])
async def run_agent(
    agent_id: Annotated[str, Query(description="Agent ID")],
    request: AgentRunRequest,
    manager: Annotated[AgentManager, Depends(get_agent_manager)],
) -> SuccessResponse[AgentRunResponse]:
    try:
        result = await manager.run_agent(
            agent_id,
            goal=request.goal,
            thread_id=request.thread_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SuccessResponse(data=AgentRunResponse(**result))


@api_router.get(
    "/agents/status",
    response_model=SuccessResponse[AgentStatusResponse],
    tags=["agents"],
)
async def get_agent_status(
    agent_id: Annotated[str, Query(description="Agent ID")],
    manager: Annotated[AgentManager, Depends(get_agent_manager)],
) -> SuccessResponse[AgentStatusResponse]:
    try:
        result = await manager.get_agent_status(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SuccessResponse(data=AgentStatusResponse(**result))


@api_router.post(
    "/agents/pause",
    response_model=SuccessResponse[AgentSummaryResponse],
    tags=["agents"],
)
async def pause_agent(
    agent_id: Annotated[str, Query(description="Agent ID")],
    request: AgentPauseRequest,
    manager: Annotated[AgentManager, Depends(get_agent_manager)],
) -> SuccessResponse[AgentSummaryResponse]:
    try:
        result = await manager.pause_agent(
            agent_id,
            thread_id=request.thread_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SuccessResponse(data=AgentSummaryResponse(**result))


@api_router.post(
    "/agents/resume",
    response_model=SuccessResponse[AgentRunResponse],
    tags=["agents"],
)
async def resume_agent(
    agent_id: Annotated[str, Query(description="Agent ID")],
    request: AgentResumeRequest,
    manager: Annotated[AgentManager, Depends(get_agent_manager)],
) -> SuccessResponse[AgentRunResponse]:
    try:
        result = await manager.resume_agent(
            agent_id,
            thread_id=request.thread_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SuccessResponse(data=AgentRunResponse(**result))


@api_router.get(
    "/tasks/{task_id}/trace",
    response_model=SuccessResponse[TaskTraceResponse],
    tags=["tasks"],
)
async def get_task_trace(
    task_id: str,
    manager: Annotated[AgentManager, Depends(get_agent_manager)],
) -> SuccessResponse[TaskTraceResponse]:
    try:
        result = await manager.get_task_trace(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SuccessResponse(data=TaskTraceResponse(**result))
