import uuid
from collections.abc import Awaitable
from contextlib import asynccontextmanager
from typing import Any, cast

import redis.asyncio as redis
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.api.routes import api_router
from src.api.schemas import ErrorResponse
from src.config import settings
from src.observability.logging import setup_logging

logger = structlog.get_logger(__name__)


async def check_db_connection(engine: AsyncEngine | None) -> bool:
    if engine is None:
        return False

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("Database health check failed", exc_info=True)
        return False


async def check_redis_connection(client: redis.Redis | None) -> bool:
    if client is None:
        return False

    try:
        awaitable_ping = client.ping()
        await cast(Awaitable[Any], awaitable_ping)
        return True
    except Exception:
        logger.warning("Redis health check failed", exc_info=True)
        return False


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    """Connect shared resources on startup and close them on shutdown."""
    setup_logging(settings.log_level)
    logger.info("Application starting up", env=settings.app_env)

    db_engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    redis_client = redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)

    app.state.db_engine = db_engine
    app.state.redis_client = redis_client

    db_connected = await check_db_connection(db_engine)
    redis_connected = await check_redis_connection(redis_client)
    logger.info("Dependencies initialized", db=db_connected, redis=redis_connected)

    yield

    logger.info("Application shutting down")

    await redis_client.aclose()
    await db_engine.dispose()


app = FastAPI(
    title="CoffeeClaw",
    version="0.1.0",
    description="Enterprise AI Agent Development Platform",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_id(request: Request, call_next: Any) -> Any:
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    with structlog.contextvars.bound_contextvars(request_id=request_id):
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response


@app.get("/health", tags=["system"])
async def health_check() -> dict[str, bool | str]:
    db_healthy = await check_db_connection(getattr(app.state, "db_engine", None))
    redis_healthy = await check_redis_connection(getattr(app.state, "redis_client", None))

    return {
        "status": "ok" if db_healthy and redis_healthy else "degraded",
        "db": db_healthy,
        "redis": redis_healthy,
    }


app.include_router(api_router, prefix="/api/v1")


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
