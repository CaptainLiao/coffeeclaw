from fastapi import FastAPI

from src.infrastructure.resources import AppResources


def get_app_resources(app: FastAPI) -> AppResources:
    return app.state.resources  # type: ignore[no-any-return]
