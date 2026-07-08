from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from rknmon.api.main import app


client = TestClient(app)


@patch("rknmon.api.agents.record_xray_probe")
@patch("rknmon.api.agents.execute", new_callable=AsyncMock)
@patch("rknmon.api.agents.fetchrow")
def test_agent_xray_results_ingest_with_node_api_key(mock_fetchrow, mock_execute, mock_record):
    mock_fetchrow.return_value = {"id": 7, "name": "edge-home", "is_active": True}
    payload = {
        "results": [
            {
                "profile_id": "ru-cascade",
                "profile_name": "RU cascade reality",
                "subscription_name": "only-cry",
                "protocol": "vless",
                "transport": "tcp",
                "security": "reality",
                "sni": "www.microsoft.com",
                "fingerprint": "chrome",
                "server_host": "vpn-node.example",
                "server_port": 443,
                "socks_port": 11001,
                "test_url": "https://cp.cloudflare.com/",
                "ok": True,
                "latency_ms": 420,
                "http_status": 204,
                "bytes_downloaded": 0,
                "error_type": None,
                "error": None,
            }
        ]
    }

    response = client.post("/agent/xray-results", headers={"X-Node-API-Key": "node-secret"}, json=payload)

    assert response.status_code == 200
    assert response.json() == {"accepted": 1, "probe_node_id": 7}
    assert mock_execute.await_count == 1
    sql = mock_execute.await_args.args[0]
    assert "INSERT INTO xray_probe_results" in sql
    assert mock_execute.await_args.args[1] == 7
    mock_record.assert_called_once()
    assert mock_record.call_args.kwargs["ok"] is True
    assert mock_record.call_args.kwargs["latency_ms"] == 420
    assert mock_record.call_args.kwargs["subscription"] == "only-cry"
