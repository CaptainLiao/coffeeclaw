import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from src.api.schemas import ErrorResponse

logger = structlog.get_logger(__name__)


def register_request_context_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def add_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        with structlog.contextvars.bound_contextvars(request_id=request_id):
            response = await call_next(request)
            response.headers["x-request-id"] = request_id
            return response


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Global exception handler caught an error",
            path=str(request.url.path),
            exc_info=exc,
        )
        response = ErrorResponse(
            code="internal_server_error",
            message="An unexpected error occurred.",
        )
        return JSONResponse(status_code=500, content=response.model_dump())
