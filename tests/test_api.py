import pytest
from fastapi.testclient import TestClient
from rknmon.api.main import app

client = TestClient(app)

class TestHealthAndRoot:
    def test_root(self):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["app"] == "rknmon"

    def test_health_db_not_configured(self):
        # health endpoint returns error when DB is unreachable
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
