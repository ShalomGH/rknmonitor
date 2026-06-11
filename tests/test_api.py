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
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data


class TestAuthMiddleware:
    def test_targets_without_api_key(self):
        response = client.get("/targets")
        assert response.status_code == 403
        assert "API key" in response.json()["detail"]

    def test_targets_with_invalid_api_key(self):
        response = client.get("/targets", headers={"X-API-Key": "wrong"})
        assert response.status_code == 403

    def test_stats_without_api_key(self):
        response = client.get("/stats")
        assert response.status_code == 403

    def test_export_without_api_key(self):
        response = client.get("/export/targets")
        assert response.status_code == 403

    def test_openapi_public(self):
        response = client.get("/openapi.json")
        assert response.status_code == 200

    def test_public_agent_install_artifacts(self):
        script = client.get("/install-agent.sh")
        assert script.status_code == 200
        assert "install-agent.sh --central" in script.text
        assert "NODE_API_KEY" in script.text

        compose = client.get("/docker-compose.agent.public.yml")
        assert compose.status_code == 200
        assert "rknmon-agent" in compose.text
        assert "build:" not in compose.text
