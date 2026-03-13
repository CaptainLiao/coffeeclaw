from typing import cast

from fastapi import FastAPI

from src.infrastructure.resources import AppResources
from src.runtime.lifecycle import AgentManager


def get_app_resources(app: FastAPI) -> AppResources:
    return cast(AppResources, app.state.resources)


def get_agent_manager_state(app: FastAPI) -> AgentManager | None:
    return cast(AgentManager | None, getattr(app.state, "agent_manager", None))
