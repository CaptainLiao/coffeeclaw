from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.core.config import Settings
from src.runtime.adapters import (
    InMemoryShortTermMemoryAdapter,
    RedisShortTermMemoryAdapter,
    ShortTermMemoryAdapter,
)
from src.runtime.checkpoint import RuntimeCheckpointer
from src.runtime.repository import RuntimeRepository, SqlRuntimeRepository


@dataclass
class RuntimeBackendResources:
    db_engine: AsyncEngine | None
    redis_client: redis.Redis | None
    runtime_repository: RuntimeRepository
    memory_adapter: ShortTermMemoryAdapter
    runtime_checkpointer: RuntimeCheckpointer


@dataclass(frozen=True)
class BackendRequirements:
    sql_engine: bool = False
    redis: bool = False

    def merge(self, other: "BackendRequirements") -> "BackendRequirements":
        return BackendRequirements(
            sql_engine=self.sql_engine or other.sql_engine,
            redis=self.redis or other.redis,
        )


T = TypeVar("T")


@dataclass(frozen=True)
class RepositoryBuilder:
    name: str
    requirements: BackendRequirements
    build: Callable[..., RuntimeRepository]


@dataclass(frozen=True)
class MemoryBuilder:
    name: str
    requirements: BackendRequirements
    build: Callable[..., ShortTermMemoryAdapter]


@dataclass(frozen=True)
class CheckpointerBuilder:
    name: str
    requirements: BackendRequirements
    build: Callable[..., RuntimeCheckpointer]


def _require_non_empty(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise RuntimeError(f"{field_name} is required.")
    return normalized


def _resolve_backend(
    value: str,
    *,
    field_name: str,
    builders: dict[str, T],
) -> T:
    normalized = value.strip().lower()
    if normalized not in builders:
        supported_text = ", ".join(builders)
        raise RuntimeError(
            f"Unsupported {field_name}: {value!r}. Supported values: {supported_text}."
        )
    return builders[normalized]


def _build_postgres_repository(
    settings: Settings,
    *,
    sql_engine: AsyncEngine | None,
    redis_client: redis.Redis | None,
) -> RuntimeRepository:
    _ = (settings, redis_client)
    if sql_engine is None:
        raise RuntimeError("runtime_repository_backend requires a SQL engine.")
    return SqlRuntimeRepository(sql_engine)


def _build_inmemory_repository(
    settings: Settings,
    *,
    sql_engine: AsyncEngine | None,
    redis_client: redis.Redis | None,
) -> RuntimeRepository:
    _ = (settings, sql_engine, redis_client)
    from src.runtime.repository import InMemoryRuntimeRepository

    return InMemoryRuntimeRepository()


def _build_redis_memory(
    settings: Settings,
    *,
    sql_engine: AsyncEngine | None,
    redis_client: redis.Redis | None,
) -> ShortTermMemoryAdapter:
    _ = (settings, sql_engine)
    if redis_client is None:
        raise RuntimeError("shortterm_memory_backend=redis requires redis_url.")
    return RedisShortTermMemoryAdapter(redis_client)


def _build_inmemory_shortterm(
    settings: Settings,
    *,
    sql_engine: AsyncEngine | None,
    redis_client: redis.Redis | None,
) -> ShortTermMemoryAdapter:
    _ = (settings, sql_engine, redis_client)
    return InMemoryShortTermMemoryAdapter()


def _build_postgres_checkpointer(
    settings: Settings,
    *,
    sql_engine: AsyncEngine | None,
    redis_client: redis.Redis | None,
) -> RuntimeCheckpointer:
    _ = (sql_engine, redis_client)
    return RuntimeCheckpointer(
        sql_dsn=_require_non_empty(settings.sql_dsn, field_name="sql_dsn"),
        in_memory=False,
    )


def _build_memory_checkpointer(
    settings: Settings,
    *,
    sql_engine: AsyncEngine | None,
    redis_client: redis.Redis | None,
) -> RuntimeCheckpointer:
    _ = (settings, sql_engine, redis_client)
    return RuntimeCheckpointer(in_memory=True)


REPOSITORY_BUILDERS: dict[str, RepositoryBuilder] = {
    "postgres": RepositoryBuilder(
        name="postgres",
        requirements=BackendRequirements(sql_engine=True),
        build=_build_postgres_repository,
    ),
    "memory": RepositoryBuilder(
        name="memory",
        requirements=BackendRequirements(),
        build=_build_inmemory_repository,
    ),
}

MEMORY_BUILDERS: dict[str, MemoryBuilder] = {
    "redis": MemoryBuilder(
        name="redis",
        requirements=BackendRequirements(redis=True),
        build=_build_redis_memory,
    ),
    "memory": MemoryBuilder(
        name="memory",
        requirements=BackendRequirements(),
        build=_build_inmemory_shortterm,
    ),
}

CHECKPOINTER_BUILDERS: dict[str, CheckpointerBuilder] = {
    "postgres": CheckpointerBuilder(
        name="postgres",
        requirements=BackendRequirements(sql_engine=True),
        build=_build_postgres_checkpointer,
    ),
    "memory": CheckpointerBuilder(
        name="memory",
        requirements=BackendRequirements(),
        build=_build_memory_checkpointer,
    ),
}


def _create_sql_engine(
    settings: Settings,
    *,
    requirements: BackendRequirements,
) -> AsyncEngine | None:
    if not requirements.sql_engine:
        return None
    return create_async_engine(
        _require_non_empty(settings.sql_dsn, field_name="sql_dsn"),
        pool_pre_ping=True,
    )


def _create_redis_client(
    settings: Settings,
    *,
    requirements: BackendRequirements,
) -> redis.Redis | None:
    if not requirements.redis:
        return None
    return redis.from_url(
        _require_non_empty(settings.redis_url, field_name="redis_url"),
        encoding="utf-8",
        decode_responses=True,
    )


async def init_runtime_backends(settings: Settings) -> RuntimeBackendResources:
    repository_builder = _resolve_backend(
        settings.runtime_repository_backend,
        field_name="runtime_repository_backend",
        builders=REPOSITORY_BUILDERS,
    )
    memory_builder = _resolve_backend(
        settings.shortterm_memory_backend,
        field_name="shortterm_memory_backend",
        builders=MEMORY_BUILDERS,
    )
    checkpointer_builder = _resolve_backend(
        settings.checkpoint_backend,
        field_name="checkpoint_backend",
        builders=CHECKPOINTER_BUILDERS,
    )

    requirements = repository_builder.requirements.merge(memory_builder.requirements).merge(
        checkpointer_builder.requirements
    )
    sql_engine = _create_sql_engine(
        settings,
        requirements=requirements,
    )
    redis_client = _create_redis_client(settings, requirements=requirements)
    runtime_checkpointer: RuntimeCheckpointer | None = None
    try:
        runtime_repository = repository_builder.build(
            settings,
            sql_engine=sql_engine,
            redis_client=redis_client,
        )
        memory_adapter = memory_builder.build(
            settings,
            sql_engine=sql_engine,
            redis_client=redis_client,
        )
        runtime_checkpointer = checkpointer_builder.build(
            settings,
            sql_engine=sql_engine,
            redis_client=redis_client,
        )
        await runtime_checkpointer.initialize()
        return RuntimeBackendResources(
            db_engine=sql_engine,
            redis_client=redis_client,
            runtime_repository=runtime_repository,
            memory_adapter=memory_adapter,
            runtime_checkpointer=runtime_checkpointer,
        )
    except Exception:
        if runtime_checkpointer is not None:
            await runtime_checkpointer.close()
        if redis_client is not None:
            await redis_client.aclose()
        if sql_engine is not None:
            await sql_engine.dispose()
        raise


async def close_runtime_backends(resources: RuntimeBackendResources) -> None:
    await resources.runtime_checkpointer.close()
    if resources.redis_client is not None:
        await resources.redis_client.aclose()
    if resources.db_engine is not None:
        await resources.db_engine.dispose()
