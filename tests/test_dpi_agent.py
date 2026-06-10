from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from rknmon.api.main import app
from rknmon.agent.dpi import parse_target_list

client = TestClient(app)


def test_parse_dpi_targets():
    targets = parse_target_list("YouTube=www.youtube.com,Example=example.org:8443,https://github.com/")

    assert targets[0].name == "YouTube"
    assert targets[0].host == "www.youtube.com"
    assert targets[0].port == 443
    assert targets[1].name == "Example"
    assert targets[1].host == "example.org"
    assert targets[1].port == 8443
    assert targets[2].host == "github.com"


@patch("rknmon.api.agents.record_dpi_probe")
@patch("rknmon.api.agents.execute", new_callable=AsyncMock)
@patch("rknmon.api.agents.fetchrow")
def test_agent_dpi_results_ingest_with_node_api_key(mock_fetchrow, mock_execute, mock_record):
    mock_fetchrow.return_value = {"id": 7, "name": "rpi-home", "is_active": True}
    payload = {
        "results": [
            {
                "checker": "l4-25",
                "target": "YouTube",
                "method": "tcp_payload_send",
                "ok": False,
                "latency_ms": 1200,
                "http_status": None,
                "error_type": "connection_reset",
                "error": "connection reset by peer",
                "details": {"host": "www.youtube.com", "bytes_sent": 4096},
            }
        ]
    }

    response = client.post("/agent/dpi-results", headers={"X-Node-API-Key": "node-secret"}, json=payload)

    assert response.status_code == 200
    assert response.json() == {"accepted": 1, "probe_node_id": 7}
    assert mock_execute.await_count == 1
    sql = mock_execute.await_args.args[0]
    assert "INSERT INTO dpi_probe_results" in sql
    assert mock_execute.await_args.args[1] == 7
    mock_record.assert_called_once()
    assert mock_record.call_args.kwargs["agent"] == "rpi-home"
    assert mock_record.call_args.kwargs["checker"] == "l4-25"
    assert mock_record.call_args.kwargs["ok"] is False
