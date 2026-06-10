import asyncio
import json
import os
import time
from pathlib import Path
from typing import Awaitable, Callable

from rknmon.agent.dpi import (
    parse_target_list,
    probe_cidrwhitelist,
    probe_dns_interference,
    probe_l4_25,
)
from rknmon.agent.xray import XrayProfile, build_xray_config, load_profiles_from_urls
from rknmon.probes.dns_probe import probe_dns as default_probe_dns
from rknmon.probes.http_probe import probe_http as default_probe_http


async def run_probe_cycle(
    client,
    probe_http: Callable[[str], Awaitable[dict]] = default_probe_http,
    probe_dns: Callable[[str], Awaitable[dict]] = default_probe_dns,
) -> dict:
    await client.register()
    await client.heartbeat()
    targets = await client.fetch_targets()
    semaphore = asyncio.Semaphore(int(os.getenv("PROBE_CONCURRENCY", "20")))

    async def probe_target(target: dict) -> list[dict]:
        async with semaphore:
            target_results: list[dict] = []

            http_result = await probe_http(target["url"])
            target_results.append(
                {
                    "target_id": target["id"],
                    "probe_type": "http",
                    "status_code": http_result.get("status_code"),
                    "response_time_ms": http_result.get("response_time_ms"),
                    "body_hash": http_result.get("body_hash"),
                    "error": http_result.get("error"),
                    "resolver": None,
                    "result": http_result.get("result", http_result),
                }
            )

            dns_result = await probe_dns(target["domain"])
            target_results.append(
                {
                    "target_id": target["id"],
                    "probe_type": "dns",
                    "status_code": dns_result.get("status_code"),
                    "response_time_ms": dns_result.get("response_time_ms"),
                    "body_hash": dns_result.get("body_hash"),
                    "error": dns_result.get("error"),
                    "resolver": dns_result.get("resolver"),
                    "result": dns_result.get("result", dns_result),
                }
            )
            return target_results

    gathered = await asyncio.gather(*(probe_target(target) for target in targets), return_exceptions=True)
    results: list[dict] = []
    for item in gathered:
        if isinstance(item, BaseException):
            continue
        results.extend(item)

    return await client.submit_results(results)


def write_xray_config(
    profiles: list[XrayProfile], config_path: str | Path, socks_start_port: int = 11001
) -> list[dict]:
    config, assignments = build_xray_config(profiles, socks_start_port=socks_start_port)
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2))
    return assignments


async def wait_for_tcp_ports(
    host: str,
    ports: list[int],
    timeout_seconds: float = 60,
    interval_seconds: float = 0.5,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    pending = set(ports)
    while pending and time.monotonic() < deadline:
        reachable: set[int] = set()
        for port in pending:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port), timeout=min(interval_seconds, 1)
                )
                writer.close()
                await writer.wait_closed()
                reachable.add(port)
            except asyncio.TimeoutError:
                continue
            except OSError:
                continue
        pending -= reachable
        if pending:
            await asyncio.sleep(interval_seconds)
    if pending:
        raise TimeoutError(f"Timed out waiting for Xray SOCKS ports on {host}: {sorted(pending)}")


async def default_probe_xray_profile(assignment: dict, test_url: str) -> dict:
    started = time.monotonic()
    proxy = f"socks5h://127.0.0.1:{assignment['socks_port']}"
    cmd = [
        "curl",
        "--silent",
        "--show-error",
        "--location",
        "--max-time",
        "20",
        "--proxy",
        proxy,
        "--output",
        "/dev/null",
        "--write-out",
        "%{http_code} %{size_download}",
        test_url,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "latency_ms": None,
            "http_status": None,
            "bytes_downloaded": None,
            "error_type": "curl_missing",
            "error": str(exc),
        }

    latency_ms = int((time.monotonic() - started) * 1000)
    output = stdout.decode(errors="replace").strip().split()
    http_status = int(output[0]) if output and output[0].isdigit() else None
    bytes_downloaded = int(output[1]) if len(output) > 1 and output[1].isdigit() else None
    ok = proc.returncode == 0 and http_status is not None and 200 <= http_status < 400
    stderr_text = stderr.decode(errors="replace").strip() or None
    return {
        "ok": ok,
        "latency_ms": latency_ms if ok else None,
        "http_status": http_status,
        "bytes_downloaded": bytes_downloaded,
        "error_type": None if ok else "curl_failed",
        "error": None if ok else stderr_text,
    }


async def run_xray_probe_cycle(
    client,
    subscription_urls: list[str],
    test_url: str,
    subscription_names: list[str] | None = None,
    socks_start_port: int = 11001,
    fetch_profiles: Callable[..., Awaitable[list[XrayProfile]]] = load_profiles_from_urls,
    probe_profile: Callable[[dict, str], Awaitable[dict]] = default_probe_xray_profile,
    config_path: str | Path | None = None,
    wait_for_socks: bool = False,
    xray_host: str = "127.0.0.1",
    ready_timeout_seconds: float = 60,
) -> dict:
    await client.register()
    await client.heartbeat()
    try:
        profiles = await fetch_profiles(subscription_urls, subscription_names=subscription_names)
    except TypeError:
        profiles = await fetch_profiles(subscription_urls)
    if config_path is not None:
        assignments = write_xray_config(profiles, config_path, socks_start_port=socks_start_port)
    else:
        _, assignments = build_xray_config(profiles, socks_start_port=socks_start_port)
    if wait_for_socks and assignments:
        await wait_for_tcp_ports(
            xray_host,
            [assignment["socks_port"] for assignment in assignments],
            timeout_seconds=ready_timeout_seconds,
        )

    results: list[dict] = []
    for assignment in assignments:
        probe_result = await probe_profile(assignment, test_url)
        results.append(
            {
                "profile_id": assignment["profile_id"],
                "profile_name": assignment["profile_name"],
                "subscription_name": assignment.get("subscription_name") or "default",
                "protocol": assignment["protocol"],
                "transport": assignment.get("transport"),
                "security": assignment.get("security"),
                "sni": assignment.get("sni"),
                "fingerprint": assignment.get("fingerprint"),
                "server_host": assignment["host"],
                "server_port": assignment["port"],
                "socks_port": assignment["socks_port"],
                "test_url": test_url,
                **probe_result,
            }
        )
    return await client.submit_xray_results(results)


async def run_dpi_probe_cycle(
    client,
    target_specs: list[str],
    whitelisted_urls: list[str],
    regular_urls: list[str],
    timeout_seconds: float = 10.0,
    l4_payload_bytes: int = 65536,
) -> dict:
    await client.register()
    await client.heartbeat()
    targets = parse_target_list(",".join(target_specs))
    results: list[dict] = []
    cidr_results, dns_results, l4_results = await asyncio.gather(
        probe_cidrwhitelist(whitelisted_urls, regular_urls, timeout_seconds),
        probe_dns_interference(targets, timeout_seconds),
        probe_l4_25(targets, timeout_seconds, l4_payload_bytes),
    )
    results.extend(cidr_results)
    results.extend(dns_results)
    results.extend(l4_results)
    return await client.submit_dpi_results(results)
