from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

import asyncpg
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

EXPECTED_CHECKPOINT_SCHEMA_VERSION = len(AsyncPostgresSaver.MIGRATIONS) - 1


def to_checkpoint_dsn(sql_dsn: str) -> str:
    parsed = urlparse(sql_dsn)
    scheme = parsed.scheme.replace("+asyncpg", "")
    return urlunparse(parsed._replace(scheme=scheme))


async def assert_checkpoint_schema_version(sql_dsn: str) -> None:
    connection = await asyncpg.connect(to_checkpoint_dsn(sql_dsn))
    try:
        version = await connection.fetchval("SELECT MAX(v) FROM checkpoint_migrations")
    except asyncpg.UndefinedTableError as exc:
        raise RuntimeError(
            "Checkpoint schema is not initialized. Run alembic migrations before starting the app."
        ) from exc
    finally:
        await connection.close()

    if not isinstance(version, int):
        raise RuntimeError(
            "Checkpoint schema version is missing. Run alembic migrations before starting the app."
        )
    if version != EXPECTED_CHECKPOINT_SCHEMA_VERSION:
        raise RuntimeError(
            "Checkpoint schema version mismatch: "
            f"database={version}, expected={EXPECTED_CHECKPOINT_SCHEMA_VERSION}. "
            "Update Alembic migrations to match the installed "
            "langgraph-checkpoint-postgres version."
        )


@dataclass
class RuntimeCheckpointer:
    sql_dsn: str | None = None
    in_memory: bool = False

    def __post_init__(self) -> None:
        self._context: AbstractAsyncContextManager[AsyncPostgresSaver] | None = None
        self._checkpointer: BaseCheckpointSaver[Any] | None = None

    async def initialize(self) -> BaseCheckpointSaver[Any]:
        if self._checkpointer is not None:
            return self._checkpointer

        if self.in_memory or self.sql_dsn is None:
            self._checkpointer = InMemorySaver()
            return self._checkpointer

        await assert_checkpoint_schema_version(self.sql_dsn)
        self._context = AsyncPostgresSaver.from_conn_string(to_checkpoint_dsn(self.sql_dsn))
        checkpointer = await self._context.__aenter__()
        self._checkpointer = checkpointer
        return checkpointer

    def get_checkpointer(self) -> BaseCheckpointSaver[Any]:
        if self._checkpointer is None:
            if self.in_memory:
                self._checkpointer = InMemorySaver()
            else:
                raise RuntimeError("RuntimeCheckpointer is not initialized.")
        return self._checkpointer

    async def close(self) -> None:
        if self._context is not None:
            await self._context.__aexit__(None, None, None)
            self._context = None
        self._checkpointer = None
