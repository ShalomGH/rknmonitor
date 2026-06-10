import asyncio
import base64
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from rknmon.agent.runner import run_xray_probe_cycle, wait_for_tcp_ports, write_xray_config


@pytest.mark.asyncio
async def test_run_xray_probe_cycle_loads_subscriptions_probes_profiles_and_submits_results():
    client = AsyncMock()
    sub = base64.b64encode(
        "\n".join(
            [
                "vless://11111111-1111-1111-1111-111111111111@ru.example.com:443?type=tcp&security=reality&sni=www.microsoft.com&fp=chrome#ru-cascade",
                "trojan://secret@de.example.net:443?security=tls&type=ws&sni=cdn.example.net#de-direct",
            ]
        ).encode()
    ).decode()

    async def fake_fetch(urls):
        assert urls == ["https://sub.example.local/sub"]
        from rknmon.agent.xray import parse_subscription_text

        return parse_subscription_text(sub, subscription_name="only-cry")

    async def fake_probe(assignment, test_url):
        return {
            "ok": assignment["profile_id"] == "ru-cascade",
            "latency_ms": 123 if assignment["profile_id"] == "ru-cascade" else None,
            "http_status": 204 if assignment["profile_id"] == "ru-cascade" else None,
            "bytes_downloaded": 0,
            "error_type": None if assignment["profile_id"] == "ru-cascade" else "timeout",
            "error": None if assignment["profile_id"] == "ru-cascade" else "timed out",
        }

    result = await run_xray_probe_cycle(
        client=client,
        subscription_urls=["https://sub.example.local/sub"],
        test_url="https://cp.cloudflare.com/",
        socks_start_port=11001,
        fetch_profiles=fake_fetch,
        probe_profile=fake_probe,
    )

    client.register.assert_awaited_once()
    client.heartbeat.assert_awaited_once()
    client.submit_xray_results.assert_awaited_once()
    payload = client.submit_xray_results.await_args.args[0]
    assert result == client.submit_xray_results.return_value
    assert [p["profile_id"] for p in payload] == ["ru-cascade", "de-direct"]
    assert payload[0]["server_host"] == "ru.example.com"
    assert payload[0]["subscription_name"] == "only-cry"
    assert payload[0]["socks_port"] == 11001
    assert payload[1]["ok"] is False
    assert payload[1]["error_type"] == "timeout"


def test_write_xray_config_writes_config_and_returns_assignments(tmp_path: Path):
    from rknmon.agent.xray import parse_subscription_text

    profiles = parse_subscription_text(
        "vless://11111111-1111-1111-1111-111111111111@ru.example.com:443?type=tcp&security=reality#ru-cascade"
    )
    path = tmp_path / "xray.generated.json"

    assignments = write_xray_config(profiles, path, socks_start_port=12000)

    config = json.loads(path.read_text())
    assert assignments[0]["subscription_name"] == "default"
    assert assignments[0]["socks_port"] == 12000
    assert config["inbounds"][0]["port"] == 12000


@pytest.mark.asyncio
async def test_wait_for_tcp_ports_waits_until_all_ports_are_reachable():
    server_one = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    server_two = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port_one = server_one.sockets[0].getsockname()[1]
    port_two = server_two.sockets[0].getsockname()[1]
    try:
        await wait_for_tcp_ports("127.0.0.1", [port_one, port_two], timeout_seconds=1, interval_seconds=0.01)
    finally:
        server_one.close()
        server_two.close()
        await server_one.wait_closed()
        await server_two.wait_closed()


@pytest.mark.asyncio
async def test_wait_for_tcp_ports_times_out_when_port_is_not_reachable():
    with pytest.raises(TimeoutError, match="Timed out waiting for Xray SOCKS ports"):
        await wait_for_tcp_ports("127.0.0.1", [9], timeout_seconds=0.05, interval_seconds=0.01)
