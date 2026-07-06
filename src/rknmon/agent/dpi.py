from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import aiohttp


@dataclass(frozen=True)
class DpiTarget:
    name: str
    host: str
    port: int = 443
    url: str | None = None


def parse_target_spec(spec: str, default_port: int = 443) -> DpiTarget:
    raw = spec.strip()
    if not raw:
        raise ValueError("empty target spec")
    name = raw
    value = raw
    if "=" in raw:
        name, value = raw.split("=", 1)
        name = name.strip()
        value = value.strip()
    url = value if value.startswith(("http://", "https://")) else None
    if url:
        parsed = urlparse(url)
        host = parsed.hostname or value
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return DpiTarget(name=name or host, host=host, port=port, url=url)
    if ":" in value and value.rsplit(":", 1)[1].isdigit():
        host, port_s = value.rsplit(":", 1)
        return DpiTarget(name=name or host, host=host, port=int(port_s), url=f"https://{host}/")
    return DpiTarget(name=name or value, host=value, port=default_port, url=f"https://{value}/")


def parse_target_list(raw: str) -> list[DpiTarget]:
    targets: list[DpiTarget] = []
    for item in raw.split(","):
        item = item.strip()
        if item:
            targets.append(parse_target_spec(item))
    return targets


def _classify_error(error: str | None) -> str | None:
    if not error:
        return None
    lower = error.lower()
    if "timed out" in lower or "timeout" in lower:
        return "timeout"
    if "refused" in lower:
        return "connection_refused"
    if "reset" in lower or "broken pipe" in lower:
        return "connection_reset"
    if "name or service" in lower or "temporary failure" in lower:
        return "dns_failed"
    return "probe_failed"


BLOCKPAGE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b451\b",
        r"access\s+(?:to\s+)?(?:denied|restricted)",
        r"blocked\s+by",
        r"internet\s+censorship",
        r"роскомнадзор|ркн",
        r"доступ\s+(?:к\s+)?(?:информационному\s+ресурсу\s+)?ограничен",
        r"доступ\s+запрещ[её]н",
        r"заблокирован",
        r"единый\s+реестр",
    )
]


def _detect_blockpage(status: int, body: str) -> str | None:
    if status in {403, 451}:
        return "http_block"
    sample = body[:8192]
    for pattern in BLOCKPAGE_PATTERNS:
        if pattern.search(sample):
            return "blockpage_signature"
    return None


async def _http_head(url: str, timeout_seconds: float) -> dict[str, Any]:
    """Probe HTTP reachability and detect common ISP/RKN block pages.

    Earlier versions treated any HTTP status <500 as OK. That hides the most
    common failure mode: provider block pages return 200/302/403/451, so the
    dashboard stayed green while real devices in the same network were blocked.
    We now fetch a small body sample and classify block-page signatures.
    """
    started = time.monotonic()
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; rknmon-dpi-checker/0.2)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Range": "bytes=0-8191",
    }
    try:
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False, headers=headers) as session:
            async with session.get(url, allow_redirects=True) as resp:
                raw = await resp.content.read(8192)
                text = raw.decode(errors="replace")
                latency_ms = int((time.monotonic() - started) * 1000)
                block_error = _detect_blockpage(resp.status, text)
                ok = 200 <= resp.status < 400 and block_error is None
                return {
                    "ok": ok,
                    "latency_ms": latency_ms,
                    "http_status": resp.status,
                    "error_type": block_error if block_error else (None if ok else "http_status"),
                    "error": None if ok else f"HTTP {resp.status}",
                    "details": {
                        "final_url": str(resp.url),
                        "body_sample": text[:500],
                        "block_signature": block_error,
                    },
                }
    except Exception as exc:
        latency_ms = int((time.monotonic() - started) * 1000)
        error = str(exc) or exc.__class__.__name__
        return {
            "ok": False,
            "latency_ms": latency_ms,
            "http_status": None,
            "error_type": _classify_error(error),
            "error": error,
            "details": {"exception": exc.__class__.__name__},
        }


async def probe_cidrwhitelist(
    whitelisted_urls: list[str], regular_urls: list[str], timeout_seconds: float
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for group, urls in (("whitelisted", whitelisted_urls), ("regular", regular_urls)):
        for url in urls:
            res = await _http_head(url, timeout_seconds)
            results.append(
                {
                    "checker": "cidrwhitelist",
                    "target": url,
                    "method": group,
                    "ok": res["ok"],
                    "latency_ms": res["latency_ms"],
                    "http_status": res["http_status"],
                    "error_type": res["error_type"],
                    "error": res["error"],
                    "details": {"url": url, "group": group, **res.get("details", {})},
                }
            )
    whitelist_ok = any(r["ok"] for r in results if r["method"] == "whitelisted")
    regular_ok = any(r["ok"] for r in results if r["method"] == "regular")
    results.append(
        {
            "checker": "cidrwhitelist",
            "target": "summary",
            "method": "heuristic",
            "ok": not (whitelist_ok and not regular_ok),
            "latency_ms": None,
            "http_status": None,
            "error_type": "cidr_whitelist_suspected" if whitelist_ok and not regular_ok else None,
            "error": None,
            "details": {"whitelist_ok": whitelist_ok, "regular_ok": regular_ok},
        }
    )
    return results


async def _resolve_system(host: str, timeout_seconds: float) -> list[str]:
    loop = asyncio.get_running_loop()

    def resolve() -> list[str]:
        infos = socket.getaddrinfo(host, 443, family=socket.AF_INET, type=socket.SOCK_STREAM)
        return sorted({item[4][0] for item in infos})

    return await asyncio.wait_for(loop.run_in_executor(None, resolve), timeout=timeout_seconds)


async def _resolve_doh(host: str, timeout_seconds: float) -> list[str]:
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    headers = {"accept": "application/dns-json"}
    url = "https://cloudflare-dns.com/dns-query"
    params = {"name": host, "type": "A"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers, trust_env=True) as session:
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
    return sorted({a["data"] for a in data.get("Answer", []) if a.get("type") == 1 and a.get("data")})


def _looks_block_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


async def probe_dns_interference(targets: list[DpiTarget], timeout_seconds: float) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for target in targets:
        started = time.monotonic()
        details: dict[str, Any] = {"host": target.host}
        ok = False
        error_type = None
        error = None
        try:
            system_ips, doh_ips = await asyncio.gather(
                _resolve_system(target.host, timeout_seconds),
                _resolve_doh(target.host, timeout_seconds),
            )
            system_set = set(system_ips)
            doh_set = set(doh_ips)
            dns_overlap = bool(system_set & doh_set)
            block_ips = sorted(ip for ip in system_set if _looks_block_ip(ip))
            details.update(
                {
                    "system_ips": system_ips,
                    "doh_ips": doh_ips,
                    "dns_overlap": dns_overlap,
                    "block_like_system_ips": block_ips,
                }
            )
            if not system_ips or not doh_ips:
                error_type = "dns_empty_response"
            elif block_ips:
                error_type = "dns_block_ip"
            elif not dns_overlap:
                error_type = "dns_mismatch"
            ok = error_type is None
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
            error_type = _classify_error(error) or "dns_failed"
            details["exception"] = exc.__class__.__name__
        results.append(
            {
                "checker": "dns",
                "target": target.name,
                "method": "system_vs_doh",
                "ok": ok,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "http_status": None,
                "error_type": error_type,
                "error": error,
                "details": details,
            }
        )
    return results


async def probe_l4_25_target(target: DpiTarget, timeout_seconds: float, payload_bytes: int) -> dict[str, Any]:
    started = time.monotonic()
    sent = 0
    error = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(target.host, target.port), timeout=timeout_seconds
        )
        try:
            chunk = b"0" * min(4096, payload_bytes)
            while sent < payload_bytes:
                to_send = min(len(chunk), payload_bytes - sent)
                writer.write(chunk[:to_send])
                await asyncio.wait_for(writer.drain(), timeout=timeout_seconds)
                sent += to_send
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
    except Exception as exc:
        error = str(exc) or exc.__class__.__name__
    ok = sent >= payload_bytes
    return {
        "checker": "l4-25",
        "target": target.name,
        "method": "tcp_payload_send",
        "ok": ok,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "http_status": None,
        "error_type": None if ok else (_classify_error(error) or "l4_25_failed"),
        "error": None if ok else error,
        "details": {"host": target.host, "port": target.port, "bytes_sent": sent, "payload_bytes": payload_bytes},
    }


async def probe_l4_25(targets: list[DpiTarget], timeout_seconds: float, payload_bytes: int) -> list[dict[str, Any]]:
    return [await probe_l4_25_target(target, timeout_seconds, payload_bytes) for target in targets]
