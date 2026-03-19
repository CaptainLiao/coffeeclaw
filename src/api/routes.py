from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import get_agent_manager, get_orchestrator_manager
from src.api.schemas import (
    AgentPauseRequest,
    AgentResumeRequest,
    AgentRunAcceptedResponse,
    AgentRunRequest,
    AgentStatusResponse,
    AgentSummaryResponse,
    CreateAgentRequest,
    OrchestratorAgentResponse,
    OrchestratorRunRequest,
    OrchestratorRunResponse,
    SkillSummaryResponse,
    SuccessResponse,
    TaskTraceResponse,
    ToolDefinitionResponse,
    ToolTestRequest,
    ToolTestResponse,
)
from src.orchestrator.supervisor import SupervisorOrchestrator
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


@api_router.post(
    "/agents/run",
    response_model=SuccessResponse[AgentRunAcceptedResponse],
    tags=["agents"],
)
async def run_agent(
    agent_id: Annotated[str, Query(description="Agent ID")],
    request: AgentRunRequest,
    manager: Annotated[AgentManager, Depends(get_agent_manager)],
) -> SuccessResponse[AgentRunAcceptedResponse]:
    try:
        result = await manager.start_agent_run(
            agent_id,
            goal=request.goal,
            thread_id=request.thread_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SuccessResponse(data=AgentRunAcceptedResponse(**result))


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
    response_model=SuccessResponse[AgentRunAcceptedResponse],
    tags=["agents"],
)
async def resume_agent(
    agent_id: Annotated[str, Query(description="Agent ID")],
    request: AgentResumeRequest,
    manager: Annotated[AgentManager, Depends(get_agent_manager)],
) -> SuccessResponse[AgentRunAcceptedResponse]:
    try:
        result = await manager.start_agent_resume(
            agent_id,
            thread_id=request.thread_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SuccessResponse(data=AgentRunAcceptedResponse(**result))


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


@api_router.get(
    "/tools",
    response_model=SuccessResponse[list[ToolDefinitionResponse]],
    tags=["tools"],
)
async def list_tools(
    manager: Annotated[AgentManager, Depends(get_agent_manager)],
) -> SuccessResponse[list[ToolDefinitionResponse]]:
    return SuccessResponse(
        data=[ToolDefinitionResponse(**item) for item in manager.list_tools()]
    )


@api_router.get(
    "/tools/{tool_name}",
    response_model=SuccessResponse[ToolDefinitionResponse],
    tags=["tools"],
)
async def get_tool(
    tool_name: str,
    manager: Annotated[AgentManager, Depends(get_agent_manager)],
) -> SuccessResponse[ToolDefinitionResponse]:
    tool = manager.get_tool(tool_name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"Tool {tool_name} not found.")
    return SuccessResponse(data=ToolDefinitionResponse(**tool))


@api_router.post(
    "/tools/{tool_name}/test",
    response_model=SuccessResponse[ToolTestResponse],
    tags=["tools"],
)
async def test_tool(
    tool_name: str,
    request: ToolTestRequest,
    manager: Annotated[AgentManager, Depends(get_agent_manager)],
) -> SuccessResponse[ToolTestResponse]:
    result = await manager.test_tool(
        tool_name=tool_name,
        input_params=request.input_params,
        agent_config=request.agent_config,
    )
    return SuccessResponse(data=ToolTestResponse(**result))


@api_router.get(
    "/skills",
    response_model=SuccessResponse[list[SkillSummaryResponse]],
    tags=["skills"],
)
async def list_skills(
    manager: Annotated[AgentManager, Depends(get_agent_manager)],
) -> SuccessResponse[list[SkillSummaryResponse]]:
    return SuccessResponse(
        data=[SkillSummaryResponse(**item) for item in manager.list_skills()]
    )


@api_router.get(
    "/orchestrator/agents",
    response_model=SuccessResponse[list[OrchestratorAgentResponse]],
    tags=["orchestrator"],
)
async def list_orchestrator_agents(
    manager: Annotated[SupervisorOrchestrator, Depends(get_orchestrator_manager)],
) -> SuccessResponse[list[OrchestratorAgentResponse]]:
    agents = await manager.list_agents()
    return SuccessResponse(
        data=[OrchestratorAgentResponse(**item) for item in agents]
    )


@api_router.post(
    "/orchestrator/run",
    response_model=SuccessResponse[OrchestratorRunResponse],
    tags=["orchestrator"],
)
async def run_orchestrator(
    request: OrchestratorRunRequest,
    manager: Annotated[SupervisorOrchestrator, Depends(get_orchestrator_manager)],
) -> SuccessResponse[OrchestratorRunResponse]:
    try:
        result = await manager.run(goal=request.goal, thread_id=request.thread_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SuccessResponse(data=OrchestratorRunResponse(**result))
