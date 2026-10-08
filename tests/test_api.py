from fastapi.testclient import TestClient

from startright.api import app

client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_db_without_database_url_returns_503(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert client.get("/health/db").status_code == 503