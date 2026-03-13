from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from src import main

client = TestClient(main.app)


async def always_healthy(_: object) -> bool:
    return True


def test_health_check(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(main, "check_db_connection", always_healthy)
    monkeypatch.setattr(main, "check_redis_connection", always_healthy)

    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["db"] is True
    assert data["redis"] is True
