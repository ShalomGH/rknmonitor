"""Tests for the resilient Xray subscription loader and health ingest.

These cover three concerns:

1. ``load_profiles_with_status`` returns merged profiles from alive
   subscriptions AND per-subscription health (with the failure reason)
   even when some URLs are dead.
2. ``run_xray_probe_cycle`` (default args) calls
   ``client.submit_subscription_health`` with that data, and a failure
   in that submission does NOT abort the cycle.
3. The ``POST /agent/subscription-health`` endpoint writes rows to
   ``xray_subscription_health`` and records Prometheus metrics.
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from rknmon.agent import runner as runner_module
from rknmon.agent.runner import run_xray_probe_cycle
from rknmon.agent.xray import load_profiles_with_status
from rknmon.api.main import app


# ---------- xray.py: load_profiles_with_status ----------


@pytest.mark.asyncio
async def test_load_profiles_with_status_returns_merged_profiles_and_per_url_status(monkeypatch):
    # Two URLs: one alive, one dead. Mock aiohttp so the public test suite
    # never depends on a real/private subscription URL.
    alive_sub = base64.b64encode(
        b"vless://11111111-1111-1111-1111-111111111111@alive.example.com:443"
        b"?type=tcp&security=reality#alive-profile"
    ).decode()

    class FakeResponse:
        def __init__(self, status: int, body: str = ""):
            self.status = status
            self._body = body

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def text(self):
            return self._body

    class FakeSession:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def get(self, url):
            if "dead.example.test" in url:
                raise TimeoutError("simulated timeout")
            return FakeResponse(200, alive_sub)

    import rknmon.agent.xray as xray_module

    monkeypatch.setattr(xray_module.aiohttp, "ClientSession", FakeSession)

    profiles, statuses = await load_profiles_with_status(
        subscription_urls=[
            "https://dead.example.test/sub/example",
            "https://alive.example.test/sub/example",
        ],
        subscription_names=["dead", "alive"],
    )

    # Profiles from the alive URL must still come through.
    assert profiles, "alive subscription must contribute profiles"
    hosts = {p.host for p in profiles}
    assert hosts == {"alive.example.com"}

    # Two statuses — one per URL, in order.
    assert len(statuses) == 2

    dead, alive_status = statuses
    assert dead["name"] == "dead"
    assert dead["ok"] is False
    assert dead["error_type"] == "timeout"
    assert dead["profiles_count"] == 0
    assert "dead.example.test" in dead["url"]

    assert alive_status["name"] == "alive"
    assert alive_status["ok"] is True
    assert alive_status["error_type"] is None
    assert alive_status["http_status"] == 200
    assert alive_status["profiles_count"] == 1


# ---------- runner.py: run_xray_probe_cycle reports health ----------


@pytest.mark.asyncio
async def test_run_xray_probe_cycle_default_submits_subscription_health():
    """With default args, the cycle must report subscription health to
    the central server (this is the production code path on the RPi)."""
    client = AsyncMock()
    # Pre-built profiles + statuses (we override the default fetcher via
    # the sentinel-aware path by passing an explicit legacy fetcher that
    # returns the profiles we want; the runner will then build a default
    # status list from the data it has).
    from rknmon.agent.xray import parse_subscription_text

    sub = base64.b64encode(
        b"vless://11111111-1111-1111-1111-111111111111@ru.example.com:443"
        b"?type=tcp&security=reality#ru-cascade"
    ).decode()

    async def fake_probe(assignment, test_url):
        return {
            "ok": True,
            "latency_ms": 100,
            "http_status": 204,
            "bytes_downloaded": 0,
            "error_type": None,
            "error": None,
        }

    # First, prove the production code path (no fetch_profiles override)
    # works end-to-end when we patch load_profiles_with_status to a stub
    # that returns a known mixed result.
    profiles = parse_subscription_text(sub, subscription_name="primary-sub")
    fake_statuses = [
        {
            "name": "primary-sub",
            "subscription_name": "primary-sub",
            "url": "https://sub.example.local/sub",
            "subscription_url": "https://sub.example.local/sub",
            "ok": True,
            "http_status": 200,
            "error_type": None,
            "error": None,
            "profiles_count": len(profiles),
        },
        {
            "name": "rpi-main",
            "subscription_name": "rpi-main",
            "url": "https://dead.example/sub",
            "subscription_url": "https://dead.example/sub",
            "ok": False,
            "http_status": None,
            "error_type": "timeout",
            "error": "fetch timeout",
            "profiles_count": 0,
        },
    ]
    with patch.object(
        runner_module,
        "load_profiles_with_status",
        AsyncMock(return_value=(profiles, fake_statuses)),
    ):
        result = await run_xray_probe_cycle(
            client=client,
            subscription_urls=["https://sub.example.local/sub", "https://dead.example/sub"],
            test_url="https://cp.cloudflare.com/",
            socks_start_port=11001,
            probe_profile=fake_probe,
        )

    # xray-results must have been submitted.
    client.submit_xray_results.assert_awaited_once()
    # AND subscription-health must have been submitted with our fake statuses.
    client.submit_subscription_health.assert_awaited_once()
    sent_items = client.submit_subscription_health.await_args.args[0]
    # Each item must have BOTH the human-friendly "name" (used in logs) and
    # the API-schema "subscription_name" / "subscription_url" aliases.
    for item in sent_items:
        assert item["subscription_name"] == item["name"]
        assert item["subscription_url"] == item["url"]
    assert sent_items == fake_statuses
    assert result == client.submit_xray_results.return_value


@pytest.mark.asyncio
async def test_run_xray_probe_cycle_swallows_subscription_health_failure():
    """If the central API is down, the xray cycle must NOT crash —
    subscription-health submission is best-effort."""
    client = AsyncMock()
    client.submit_subscription_health.side_effect = RuntimeError("central is down")

    from rknmon.agent.xray import parse_subscription_text

    sub = base64.b64encode(
        b"vless://11111111-1111-1111-1111-111111111111@ru.example.com:443"
        b"?type=tcp&security=reality#ru-cascade"
    ).decode()
    profiles = parse_subscription_text(sub, subscription_name="primary-sub")
    statuses = [
        {
            "name": "primary-sub",
            "subscription_name": "primary-sub",
            "url": "https://sub.example.local/sub",
            "subscription_url": "https://sub.example.local/sub",
            "ok": True,
            "http_status": 200,
            "error_type": None,
            "error": None,
            "profiles_count": 1,
        }
    ]

    async def fake_probe(assignment, test_url):
        return {
            "ok": True,
            "latency_ms": 50,
            "http_status": 204,
            "bytes_downloaded": 0,
            "error_type": None,
            "error": None,
        }

    with patch.object(
        runner_module,
        "load_profiles_with_status",
        AsyncMock(return_value=(profiles, statuses)),
    ):
        # Must not raise.
        result = await run_xray_probe_cycle(
            client=client,
            subscription_urls=["https://sub.example.local/sub"],
            test_url="https://cp.cloudflare.com/",
            probe_profile=fake_probe,
        )

    client.submit_xray_results.assert_awaited_once()
    client.submit_subscription_health.assert_awaited_once()
    assert result == client.submit_xray_results.return_value


# ---------- API: /agent/subscription-health ----------


api_client = TestClient(app)


@patch("rknmon.api.agents.record_subscription_health")
@patch("rknmon.api.agents.execute", new_callable=AsyncMock)
@patch("rknmon.api.agents.fetchrow")
def test_subscription_health_endpoint_writes_rows_and_records_metrics(
    mock_fetchrow, mock_execute, mock_record
):
    mock_fetchrow.return_value = {"id": 7, "name": "rpi-home", "is_active": True}

    payload = {
        "items": [
            {
                "subscription_name": "rpi-main",
                "subscription_url": "https://sub.primary.example/sub/example-token",
                "ok": False,
                "http_status": None,
                "error_type": "timeout",
                "error": "fetch timeout",
                "profiles_count": 0,
            },
            {
                "subscription_name": "rpi-secondary",
                "subscription_url": "https://sub.secondary.example/sub/example",
                "ok": True,
                "http_status": 200,
                "error_type": None,
                "error": None,
                "profiles_count": 3,
            },
        ]
    }
    response = api_client.post(
        "/agent/subscription-health",
        headers={"X-Node-API-Key": "node-secret"},
        json=payload,
    )
    assert response.status_code == 200
    assert response.json() == {"accepted": 2, "probe_node_id": 7}

    # 2 rows written, with the dead subscription recorded first.
    assert mock_execute.await_count == 2
    sql = mock_execute.await_args_list[0].args[0]
    assert "INSERT INTO xray_subscription_health" in sql
    assert mock_execute.await_args_list[0].args[1] == 7
    assert mock_execute.await_args_list[0].args[2] == "rpi-main"
    assert mock_execute.await_args_list[0].args[3] == "https://sub.primary.example/sub/example-token"
    assert mock_execute.await_args_list[0].args[4] is False  # ok

    # Metrics called twice — once per item.
    assert mock_record.call_count == 2
    dead_call = mock_record.call_args_list[0].kwargs
    assert dead_call["ok"] is False
    assert dead_call["error_type"] == "timeout"
    assert dead_call["subscription"] == "rpi-main"

    alive_call = mock_record.call_args_list[1].kwargs
    assert alive_call["ok"] is True
    assert alive_call["subscription"] == "rpi-secondary"


@patch("rknmon.api.agents.fetchrow")
def test_subscription_health_endpoint_rejects_without_api_key(mock_fetchrow):
    response = api_client.post(
        "/agent/subscription-health",
        json={"items": []},
    )
    assert response.status_code == 403
    mock_fetchrow.assert_not_called()
