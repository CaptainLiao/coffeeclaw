from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from src.core import app as app_module
from src.core.app import create_app
from src.runtime.checkpoint import RuntimeCheckpointer
from src.services import health as health_service


async def always_healthy(_: object) -> bool:
    return True


def test_health_check(monkeypatch: MonkeyPatch) -> None:
    fake_resources = type(
        "Resources",
        (),
        {
            "db_engine": object(),
            "redis_client": object(),
            "runtime_checkpointer": RuntimeCheckpointer(in_memory=True),
            "startup_health": type("Health", (), {"db": True, "redis": True})(),
        },
    )()

    async def fake_init_resources(_: object) -> object:
        return fake_resources

    async def fake_close_resources(_: object) -> None:
        return None

    monkeypatch.setattr(health_service, "check_db_connection", always_healthy)
    monkeypatch.setattr(health_service, "check_redis_connection", always_healthy)
    monkeypatch.setattr(app_module, "init_resources", fake_init_resources)
    monkeypatch.setattr(app_module, "close_resources", fake_close_resources)

    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 1
    data = payload["data"]
    assert data["status"] == "ok"
    assert data["db"] is True
    assert data["redis"] is True
