from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


def to_checkpoint_dsn(postgres_dsn: str) -> str:
    parsed = urlparse(postgres_dsn)
    scheme = parsed.scheme.replace("+asyncpg", "")
    return urlunparse(parsed._replace(scheme=scheme))


@dataclass
class RuntimeCheckpointer:
    postgres_dsn: str | None = None
    in_memory: bool = False

    def __post_init__(self) -> None:
        self._context: AbstractAsyncContextManager[AsyncPostgresSaver] | None = None
        self._checkpointer: BaseCheckpointSaver[Any] | None = None

    async def initialize(self) -> BaseCheckpointSaver[Any]:
        if self._checkpointer is not None:
            return self._checkpointer

        if self.in_memory or self.postgres_dsn is None:
            self._checkpointer = InMemorySaver()
            return self._checkpointer

        self._context = AsyncPostgresSaver.from_conn_string(to_checkpoint_dsn(self.postgres_dsn))
        checkpointer = await self._context.__aenter__()
        await checkpointer.setup()
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
