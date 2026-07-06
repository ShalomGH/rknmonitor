from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from rknmon.api.main import app
from rknmon.agent import dpi
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


@pytest.mark.asyncio
async def test_dpi_http_probe_flags_block_pages(monkeypatch):
    class FakeContent:
        async def read(self, n):
            return "Доступ к информационному ресурсу ограничен Роскомнадзор".encode()

    class FakeResponse:
        status = 200
        url = "http://blocked.example/"
        content = FakeContent()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    class FakeSession:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            assert self.kwargs["trust_env"] is False
            return self

        async def __aexit__(self, *args):
            return None

        def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(dpi.aiohttp, "ClientSession", FakeSession)

    result = await dpi._http_head("http://blocked.example/", 5)

    assert result["ok"] is False
    assert result["http_status"] == 200
    assert result["error_type"] == "blockpage_signature"
    assert result["details"]["block_signature"] == "blockpage_signature"


@pytest.mark.asyncio
async def test_dns_probe_flags_poisoned_private_ip(monkeypatch):
    async def fake_system(host, timeout):
        return ["127.0.0.1"]

    async def fake_doh(host, timeout):
        return ["93.184.216.34"]

    monkeypatch.setattr(dpi, "_resolve_system", fake_system)
    monkeypatch.setattr(dpi, "_resolve_doh", fake_doh)

    target = dpi.parse_target_spec("Example=example.com")
    result = (await dpi.probe_dns_interference([target], 5))[0]

    assert result["ok"] is False
    assert result["error_type"] == "dns_block_ip"
    assert result["details"]["block_like_system_ips"] == ["127.0.0.1"]
