import pytest
from unittest.mock import AsyncMock

from rknmon.agent.runner import run_probe_cycle


@pytest.mark.asyncio
async def test_run_probe_cycle_fetches_targets_probes_and_submits_results():
    client = AsyncMock()
    client.fetch_targets.return_value = [
        {"id": 1, "url": "https://youtube.com", "domain": "youtube.com"},
        {"id": 2, "url": "https://discord.com", "domain": "discord.com"},
    ]

    async def fake_http(url):
        return {"status_code": 200, "response_time_ms": 123, "body_hash": "abc", "error": None, "result": {"reachable": True}}

    async def fake_dns(domain):
        return {"response_time_ms": 45, "resolver": "system", "error": None, "result": {"tampered": False}}

    await run_probe_cycle(client=client, probe_http=fake_http, probe_dns=fake_dns)

    client.register.assert_awaited_once()
    client.heartbeat.assert_awaited_once()
    client.fetch_targets.assert_awaited_once()
    client.submit_results.assert_awaited_once()
    payload = client.submit_results.await_args.args[0]
    assert len(payload) == 4
    assert payload[0]["target_id"] == 1
    assert payload[1]["probe_type"] == "dns"
    assert payload[2]["target_id"] == 2
