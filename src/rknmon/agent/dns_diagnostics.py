from __future__ import annotations

import asyncio
import ipaddress
import secrets
import socket
import ssl
import struct
import time
from typing import Any

import aiohttp

from rknmon.agent.dpi import DpiTarget


_DOH_RESOLVERS = {
    "doh_cloudflare": "https://cloudflare-dns.com/dns-query",
    "doh_google": "https://dns.google/resolve",
}
_DOT_HOST = "1.1.1.1"
_DOT_TLS_NAME = "cloudflare-dns.com"
_DOT_PORT = 853


async def _resolve_system(host: str, timeout_seconds: float) -> list[str]:
    loop = asyncio.get_running_loop()

    def resolve() -> list[str]:
        infos = socket.getaddrinfo(host, 443, family=socket.AF_INET, type=socket.SOCK_STREAM)
        return sorted({item[4][0] for item in infos})

    return await asyncio.wait_for(loop.run_in_executor(None, resolve), timeout=timeout_seconds)


async def _resolve_doh(host: str, url: str, timeout_seconds: float) -> list[str]:
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    headers = {"accept": "application/dns-json"}
    params = {"name": host, "type": "A"}
    async with aiohttp.ClientSession(timeout=timeout, headers=headers, trust_env=False) as session:
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)
    return sorted(
        {
            answer["data"]
            for answer in data.get("Answer", [])
            if answer.get("type") == 1 and answer.get("data")
        }
    )


def _encode_dns_name(host: str) -> bytes:
    labels = host.rstrip(".").split(".")
    encoded = bytearray()
    for label in labels:
        raw = label.encode("idna")
        if not raw or len(raw) > 63:
            raise ValueError(f"invalid DNS label in {host!r}")
        encoded.append(len(raw))
        encoded.extend(raw)
    encoded.append(0)
    return bytes(encoded)


def _build_dns_query(host: str, query_id: int) -> bytes:
    header = struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 0)
    question = _encode_dns_name(host) + struct.pack("!HH", 1, 1)
    return header + question


def _skip_dns_name(packet: bytes, offset: int) -> int:
    while True:
        if offset >= len(packet):
            raise ValueError("truncated DNS name")
        length = packet[offset]
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(packet):
                raise ValueError("truncated DNS compression pointer")
            return offset + 2
        if length == 0:
            return offset + 1
        offset += 1 + length


def _parse_a_answers(packet: bytes, query_id: int) -> list[str]:
    if len(packet) < 12:
        raise ValueError("truncated DNS response")
    response_id, flags, qdcount, ancount, _, _ = struct.unpack_from("!HHHHHH", packet, 0)
    if response_id != query_id:
        raise ValueError("DNS transaction id mismatch")
    if flags & 0x000F:
        raise ValueError(f"DNS rcode={flags & 0x000F}")

    offset = 12
    for _ in range(qdcount):
        offset = _skip_dns_name(packet, offset)
        if offset + 4 > len(packet):
            raise ValueError("truncated DNS question")
        offset += 4

    answers: set[str] = set()
    for _ in range(ancount):
        offset = _skip_dns_name(packet, offset)
        if offset + 10 > len(packet):
            raise ValueError("truncated DNS answer")
        record_type, record_class, _, rdlength = struct.unpack_from("!HHIH", packet, offset)
        offset += 10
        if offset + rdlength > len(packet):
            raise ValueError("truncated DNS rdata")
        rdata = packet[offset : offset + rdlength]
        offset += rdlength
        if record_type == 1 and record_class == 1 and rdlength == 4:
            answers.add(socket.inet_ntoa(rdata))
    return sorted(answers)


async def _resolve_dot(host: str, timeout_seconds: float) -> list[str]:
    query_id = secrets.randbits(16)
    query = _build_dns_query(host, query_id)
    context = ssl.create_default_context()
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(
            _DOT_HOST,
            _DOT_PORT,
            ssl=context,
            server_hostname=_DOT_TLS_NAME,
        ),
        timeout=timeout_seconds,
    )
    try:
        writer.write(struct.pack("!H", len(query)) + query)
        await asyncio.wait_for(writer.drain(), timeout=timeout_seconds)
        size = struct.unpack("!H", await asyncio.wait_for(reader.readexactly(2), timeout=timeout_seconds))[0]
        packet = await asyncio.wait_for(reader.readexactly(size), timeout=timeout_seconds)
        return _parse_a_answers(packet, query_id)
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def _tcp_reachable(ip: str, port: int, timeout_seconds: float) -> bool:
    writer: asyncio.StreamWriter | None = None
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=min(timeout_seconds, 3.0),
        )
        return True
    except (asyncio.TimeoutError, OSError):
        return False
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


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


def classify_dns_evidence(
    *,
    system_ips: list[str],
    reference_answers: dict[str, list[str]],
    system_error: str | None,
    reference_errors: dict[str, str],
    tcp_reachability: dict[str, bool],
) -> tuple[bool, str | None, dict[str, Any]]:
    """Classify DNS evidence without treating ordinary CDN/GeoDNS divergence as blocking."""
    system_set = set(system_ips)
    successful_references = {
        name: sorted(set(ips)) for name, ips in reference_answers.items() if ips
    }
    reference_union = {
        ip for ips in successful_references.values() for ip in ips
    }
    overlap = sorted(system_set & reference_union)
    block_ips = sorted(ip for ip in system_set if _looks_block_ip(ip))
    system_reachable = any(tcp_reachability.get(ip, False) for ip in system_set)
    reference_reachable = any(tcp_reachability.get(ip, False) for ip in reference_union)

    evidence = {
        "system_ips": sorted(system_set),
        "reference_answers": successful_references,
        "reference_errors": reference_errors,
        "reference_source_count": len(successful_references),
        "reference_union": sorted(reference_union),
        "dns_overlap": overlap,
        "block_like_system_ips": block_ips,
        "tcp_reachability": tcp_reachability,
        "tcp_system_reachable": system_reachable,
        "tcp_reference_reachable": reference_reachable,
        "system_error": system_error,
    }

    if block_ips:
        evidence["diagnosis"] = "block_like_system_answer"
        return False, "dns_block_ip", evidence

    if system_error or not system_set:
        if len(successful_references) >= 2 and reference_reachable:
            evidence["diagnosis"] = "system_resolution_failed_references_reachable"
            return False, "dns_resolution_failure_confirmed", evidence
        evidence["diagnosis"] = "system_resolution_failure_unconfirmed"
        return False, "dns_system_failure_unconfirmed", evidence

    if overlap:
        evidence["diagnosis"] = "system_overlaps_reference"
        return True, None, evidence

    if not reference_union:
        evidence["diagnosis"] = "reference_resolvers_unavailable"
        return True, None, evidence

    # Public resolvers often return different CDN/GeoDNS edges. If the address
    # chosen by the system resolver is actually reachable, divergence alone is
    # not evidence of interference.
    if system_reachable:
        evidence["diagnosis"] = "dns_divergence_but_system_ip_reachable"
        return True, None, evidence

    if len(successful_references) >= 2 and reference_reachable:
        evidence["diagnosis"] = "system_answers_unreachable_references_reachable"
        return False, "dns_mismatch_confirmed", evidence

    evidence["diagnosis"] = "dns_divergence_inconclusive"
    return True, None, evidence


async def probe_dns_interference(
    targets: list[DpiTarget], timeout_seconds: float
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for target in targets:
        started = time.monotonic()

        system_ips: list[str] = []
        system_error: str | None = None
        try:
            system_ips = await _resolve_system(target.host, timeout_seconds)
        except Exception as exc:
            system_error = str(exc) or exc.__class__.__name__

        reference_tasks = {
            name: asyncio.create_task(_resolve_doh(target.host, url, timeout_seconds))
            for name, url in _DOH_RESOLVERS.items()
        }
        reference_tasks["dot_cloudflare"] = asyncio.create_task(
            _resolve_dot(target.host, timeout_seconds)
        )

        reference_answers: dict[str, list[str]] = {}
        reference_errors: dict[str, str] = {}
        for name, task in reference_tasks.items():
            try:
                reference_answers[name] = await task
            except Exception as exc:
                reference_errors[name] = str(exc) or exc.__class__.__name__

        reference_union = sorted(
            {ip for ips in reference_answers.values() for ip in ips}
        )
        overlap = bool(set(system_ips) & set(reference_union))
        need_tcp_confirmation = bool(system_error or not system_ips or (reference_union and not overlap))
        tcp_reachability: dict[str, bool] = {}
        if need_tcp_confirmation:
            candidates = list(dict.fromkeys(system_ips[:2] + reference_union[:2]))
            reachability = await asyncio.gather(
                *(_tcp_reachable(ip, target.port, timeout_seconds) for ip in candidates)
            )
            tcp_reachability = dict(zip(candidates, reachability))

        ok, error_type, evidence = classify_dns_evidence(
            system_ips=system_ips,
            reference_answers=reference_answers,
            system_error=system_error,
            reference_errors=reference_errors,
            tcp_reachability=tcp_reachability,
        )
        evidence["host"] = target.host
        evidence["port"] = target.port

        results.append(
            {
                "checker": "dns",
                "target": target.name,
                "method": "system_vs_doh_dot_tcp",
                "ok": ok,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "http_status": None,
                "error_type": error_type,
                "error": system_error if not ok and error_type == "dns_system_failure_unconfirmed" else None,
                "details": evidence,
            }
        )
    return results
