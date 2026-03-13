from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse, urlunparse

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver


def to_checkpoint_dsn(postgres_dsn: str) -> str:
    parsed = urlparse(postgres_dsn)
    scheme = parsed.scheme.replace("+asyncpg", "")
    return urlunparse(parsed._replace(scheme=scheme))


@dataclass
class RuntimeCheckpointer:
    postgres_dsn: str | None = None
    in_memory: bool = False

    def __post_init__(self) -> None:
        self._context: AbstractContextManager[PostgresSaver] | None = None
        self._checkpointer: BaseCheckpointSaver[Any] | None = None

    def initialize(self) -> BaseCheckpointSaver[Any]:
        if self._checkpointer is not None:
            return self._checkpointer

        if self.in_memory or self.postgres_dsn is None:
            self._checkpointer = InMemorySaver()
            return self._checkpointer

        self._context = PostgresSaver.from_conn_string(to_checkpoint_dsn(self.postgres_dsn))
        checkpointer = self._context.__enter__()
        checkpointer.setup()
        self._checkpointer = checkpointer
        return checkpointer

    def get_checkpointer(self) -> BaseCheckpointSaver[Any]:
        return self.initialize()

    def close(self) -> None:
        if self._context is not None:
            self._context.__exit__(None, None, None)
            self._context = None
        self._checkpointer = None
