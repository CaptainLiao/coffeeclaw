from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.core.config import Settings
from src.infrastructure import resources as resources_module
from src.infrastructure.runtime_backends import init_runtime_backends
from src.orchestrator.registry import AgentRegistry


def _build_settings(**overrides: str) -> Settings:
    payload = {
        "model_api_key": "test-key",
        "model_api_base": "https://example.com/v1",
        "SQL_DSN": "postgresql+asyncpg://user:pass@localhost:5432/coffeeclaw",
        "redis_url": "redis://localhost:6379/0",
        "runtime_repository_backend": "memory",
        "shortterm_memory_backend": "memory",
        "checkpoint_backend": "memory",
        "app_env": "test",
        "log_level": "INFO",
        "default_primary_model": "gpt-4o-mini",
        "default_fallback_model": "gpt-4o-mini",
        "model_timeout_seconds": 30,
        "max_retries": 2,
    }
    payload.update(overrides)
    return Settings.model_validate(payload)


@pytest.mark.asyncio
async def test_init_resources_rejects_unknown_repository_backend() -> None:
    with pytest.raises(RuntimeError, match="Unsupported runtime_repository_backend"):
        await init_runtime_backends(
            _build_settings(runtime_repository_backend="mysql")
        )


@pytest.mark.asyncio
async def test_init_resources_closes_partial_resources_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @dataclass
    class FakeCheckpointer:
        closed: bool = False

        async def initialize(self) -> None:
            return None

        async def close(self) -> None:
            self.closed = True

    fake_checkpointer = FakeCheckpointer()

    class FakeBackendResources:
        db_engine = None
        redis_client = None
        runtime_repository = object()
        memory_adapter = object()
        runtime_checkpointer = fake_checkpointer

    async def fake_init_runtime_backends(_: Settings) -> FakeBackendResources:
        return FakeBackendResources()

    def fake_from_file(_: str) -> object:
        raise RuntimeError("boom")

    async def fake_close_runtime_backends(_: object) -> None:
        await fake_checkpointer.close()

    monkeypatch.setattr(resources_module, "init_runtime_backends", fake_init_runtime_backends)
    monkeypatch.setattr(resources_module, "close_runtime_backends", fake_close_runtime_backends)
    monkeypatch.setattr(AgentRegistry, "from_file", fake_from_file)

    with pytest.raises(RuntimeError, match="boom"):
        await resources_module.init_resources(_build_settings())

    assert fake_checkpointer.closed is True
