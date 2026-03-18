from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import asyncpg
import pytest

from src.runtime.checkpoint import (
    EXPECTED_CHECKPOINT_SCHEMA_VERSION,
    RuntimeCheckpointer,
    assert_checkpoint_schema_version,
)


@pytest.mark.asyncio
async def test_postgres_checkpointer_initialize_does_not_run_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @dataclass
    class FakeSaver:
        setup_called: bool = False

        async def setup(self) -> None:
            self.setup_called = True
            raise AssertionError("setup should not be called during runtime initialization")

    class FakeContext:
        def __init__(self) -> None:
            self.saver = FakeSaver()

        async def __aenter__(self) -> FakeSaver:
            return self.saver

        async def __aexit__(self, *_args: object) -> None:
            return None

    fake_context = FakeContext()

    monkeypatch.setattr(
        "src.runtime.checkpoint.AsyncPostgresSaver.from_conn_string",
        lambda _dsn: fake_context,
    )
    async def fake_assert_version(_sql_dsn: str) -> None:
        return None

    monkeypatch.setattr(
        "src.runtime.checkpoint.assert_checkpoint_schema_version",
        fake_assert_version,
    )

    checkpointer = RuntimeCheckpointer(
        sql_dsn="postgresql+asyncpg://user:pass@localhost:5432/coffeeclaw",
        in_memory=False,
    )
    saver = await checkpointer.initialize()

    assert cast(object, saver) is fake_context.saver
    assert fake_context.saver.setup_called is False


@pytest.mark.asyncio
async def test_assert_checkpoint_schema_version_rejects_missing_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeConnection:
        async def fetchval(self, _query: str) -> object:
            raise asyncpg.UndefinedTableError("missing table")

        async def close(self) -> None:
            return None

    async def fake_connect(_dsn: str) -> FakeConnection:
        return FakeConnection()

    monkeypatch.setattr("src.runtime.checkpoint.asyncpg.connect", fake_connect)

    with pytest.raises(RuntimeError, match="Checkpoint schema is not initialized"):
        await assert_checkpoint_schema_version("postgresql://user:pass@localhost:5432/coffeeclaw")


@pytest.mark.asyncio
async def test_assert_checkpoint_schema_version_rejects_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeConnection:
        async def fetchval(self, _query: str) -> int:
            return EXPECTED_CHECKPOINT_SCHEMA_VERSION - 1

        async def close(self) -> None:
            return None

    async def fake_connect(_dsn: str) -> FakeConnection:
        return FakeConnection()

    monkeypatch.setattr("src.runtime.checkpoint.asyncpg.connect", fake_connect)

    with pytest.raises(RuntimeError, match="Checkpoint schema version mismatch"):
        await assert_checkpoint_schema_version("postgresql://user:pass@localhost:5432/coffeeclaw")
