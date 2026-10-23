from fastapi.testclient import TestClient

from backend.main import create_app
from backend.settings import Settings


def test_health_returns_ok(tmp_path) -> None:
    client = TestClient(create_app(Settings(data_dir=tmp_path)))
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
