import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.api.schemas import ErrorResponse
from src.core.config import settings

logger = structlog.get_logger(__name__)


def register_request_context_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def add_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        request.state.request_id = request_id
        with structlog.contextvars.bound_contextvars(request_id=request_id):
            response = await call_next(request)
            response.headers["x-request-id"] = request_id
            return response


def register_exception_handlers(app: FastAPI) -> None:
    def build_error_data(
        request: Request,
        *,
        error_type: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "request_id": getattr(request.state, "request_id", ""),
            "path": str(request.url.path),
            "error_type": error_type,
        }
        if extra:
            data.update(extra)
        return data

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        message = detail if isinstance(detail, str) else "Request failed."
        extra: dict[str, Any] | None = None
        if not isinstance(detail, str):
            extra = {"detail": detail}
        data = build_error_data(request, error_type="http_error", extra=extra)
        response = ErrorResponse(message=message, data=data)
        return JSONResponse(status_code=exc.status_code, content=response.model_dump())

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        response = ErrorResponse(
            message="Request validation failed.",
            data=build_error_data(
                request,
                error_type="validation_error",
                extra={"errors": exc.errors()},
            ),
        )
        return JSONResponse(status_code=422, content=response.model_dump())

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Global exception handler caught an error",
            path=str(request.url.path),
            exc_info=exc,
        )
        extra: dict[str, Any] | None = None
        if settings.app_env != "production":
            extra = {
                "exception": exc.__class__.__name__,
                "exception_message": str(exc),
            }
        response = ErrorResponse(
            message="An unexpected error occurred.",
            data=build_error_data(
                request,
                error_type="internal_error",
                extra=extra,
            ),
        )
        return JSONResponse(status_code=500, content=response.model_dump())
