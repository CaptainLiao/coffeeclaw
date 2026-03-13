from types import SimpleNamespace

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from src import main
from src.services import health as health_service

client = TestClient(main.app)


async def always_healthy(_: object) -> bool:
    return True


def test_health_check(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(health_service, "check_db_connection", always_healthy)
    monkeypatch.setattr(health_service, "check_redis_connection", always_healthy)
    main.app.state.resources = SimpleNamespace(db_engine=object(), redis_client=object())

    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["db"] is True
    assert data["redis"] is True
