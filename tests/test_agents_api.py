from fastapi.testclient import TestClient
import os
from unittest.mock import AsyncMock, patch

from rknmon.api.main import app


client = TestClient(app)


@patch("rknmon.api.agents.fetch")
@patch("rknmon.api.agents.fetchrow")
def test_agent_targets_returns_active_targets_for_valid_node_key(mock_fetchrow, mock_fetch):
    mock_fetchrow.return_value = {"id": 7, "name": "edge-home", "is_active": True}
    mock_fetch.return_value = [
        {"id": 1, "url": "https://youtube.com", "domain": "youtube.com", "category": "blocked_rkn", "is_active": True}
    ]

    response = client.get("/agent/targets", headers={"X-Node-API-Key": "node-secret"})

    assert response.status_code == 200
    assert response.json()[0]["domain"] == "youtube.com"


@patch("rknmon.api.agents.evaluate_targets", new_callable=AsyncMock)
@patch("rknmon.api.agents.fetch")
@patch("rknmon.api.agents.execute", new_callable=AsyncMock)
@patch("rknmon.api.agents.fetchrow")
def test_agent_results_ingest_with_node_api_key(mock_fetchrow, mock_execute, mock_fetch, mock_evaluate):
    mock_fetchrow.return_value = {"id": 7, "name": "edge-home", "is_active": True}
    mock_fetch.return_value = [{"id": 1, "domain": "youtube.com"}]

    payload = {
        "results": [
            {
                "target_id": 1,
                "probe_type": "http",
                "status_code": 200,
                "response_time_ms": 321,
                "body_hash": "abc",
                "error": None,
                "resolver": None,
                "result": {"reachable": True},
            },
            {
                "target_id": 1,
                "probe_type": "dns",
                "status_code": None,
                "response_time_ms": 55,
                "body_hash": None,
                "error": None,
                "resolver": "system",
                "result": {"tampered": False},
            },
        ]
    }

    response = client.post("/agent/results", headers={"X-Node-API-Key": "node-secret"}, json=payload)

    assert response.status_code == 200
    assert response.json() == {"accepted": 2, "probe_node_id": 7}
    assert mock_execute.await_count == 2
    first_call_args = mock_execute.await_args_list[0].args
    assert "INSERT INTO probes" in first_call_args[0]
    assert first_call_args[2] == 7


@patch.dict(os.environ, {"RKNMON_ALLOW_DIRECT_REGISTRATION": "true"})
@patch("rknmon.api.agents.execute", new_callable=AsyncMock)
@patch("rknmon.api.agents.fetchrow")
def test_agent_register_upserts_probe_node_and_returns_identity(mock_fetchrow, mock_execute):
    mock_fetchrow.side_effect = [
        None,
        {
            "id": 7,
            "name": "edge-home",
            "is_active": True,
            "location": "home",
            "provider": "domru",
            "last_ip": "198.51.100.10",
            "agent_version": "0.1.0",
        },
    ]

    payload = {
        "name": "edge-home",
        "location": "home",
        "provider": "domru",
        "agent_version": "0.1.0",
        "public_ip": "198.51.100.10",
    }

    response = client.post("/agent/register", headers={"X-Node-API-Key": "node-secret"}, json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["probe_node_id"] == 7
    assert body["name"] == "edge-home"
    assert body["registration"] == "legacy"
    assert mock_execute.await_count == 1
    assert "INSERT INTO probe_nodes" in mock_execute.await_args.args[0]


@patch("rknmon.api.agents.execute", new_callable=AsyncMock)
@patch("rknmon.api.agents.fetchrow")
def test_agent_heartbeat_updates_last_seen_and_returns_ack(mock_fetchrow, mock_execute):
    mock_fetchrow.return_value = {"id": 7, "name": "edge-home", "is_active": True}

    payload = {
        "agent_version": "0.1.1",
        "public_ip": "198.51.100.10",
    }

    response = client.post("/agent/heartbeat", headers={"X-Node-API-Key": "node-secret"}, json=payload)

    assert response.status_code == 200
    assert response.json() == {
        "probe_node_id": 7,
        "status": "ok",
        "poll_interval_seconds": 300,
    }
    assert mock_execute.await_count == 1
    assert "UPDATE probe_nodes" in mock_execute.await_args.args[0]
