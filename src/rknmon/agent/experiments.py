from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import ssl
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from rknmon.agent.artifacts import FailureArtifactCollector


@dataclass(frozen=True)
class ExperimentTarget:
    name: str
    url: str
    host: str
    port: int
    path: str


def parse_experiment_target(spec: str) -> ExperimentTarget:
    raw = spec.strip()
    if not raw:
        raise ValueError("empty experiment target")
    name, value = (raw.split("=", 1) if "=" in raw else (raw, raw))
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}/"
    parsed = urlparse(value)
    if not parsed.hostname:
        raise ValueError(f"invalid experiment target: {spec}")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    return ExperimentTarget(name.strip() or parsed.hostname, value, parsed.hostname, port, path)


def _ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000, 3)


def _outcome(exc: BaseException, layer: str) -> str:
    text = str(exc).lower()
    if isinstance(exc, asyncio.TimeoutError) or "timeout" in text or "timed out" in text:
        return f"{layer}_timeout"
    if "reset" in text or "broken pipe" in text:
        return f"{layer}_reset"
    if "refused" in text:
        return f"{layer}_refused"
    if isinstance(exc, ssl.SSLError):
        return f"{layer}_tls_error"
    return f"{layer}_error"


def _stage(name: str, ok: bool, duration_ms: float, outcome: str, **details: Any) -> dict:
    return {
        "stage": name,
        "ok": ok,
        "duration_ms": duration_ms,
        "outcome": outcome,
        "details": details,
    }


def _ssl_context() -> ssl.SSLContext:
    # Controlled A/B experiments isolate SNI/Host behavior, so certificate
    # validation is intentionally disabled. Use only authorized endpoints.
    # The raw application request below is HTTP/1.1, therefore do not offer h2.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_alpn_protocols(["http/1.1"])
    return ctx


async def _resolve(host: str, port: int, timeout: float) -> tuple[list[str], float]:
    started = time.monotonic()
    loop = asyncio.get_running_loop()
    infos = await asyncio.wait_for(
        loop.getaddrinfo(host, port, family=2, type=1),
        timeout=timeout,
    )
    return sorted({item[4][0] for item in infos if isinstance(item[4][0], str)}), _ms(started)


def _row(
    target: ExperimentTarget,
    checker: str,
    variant: str,
    ok: bool,
    outcome: str,
    started: float,
    stages: list[dict],
    details: dict,
) -> dict:
    return {
        "checker": checker,
        "target": target.name,
        "method": variant,
        "ok": ok,
        "latency_ms": _ms(started),
        "http_status": details.get("http_status"),
        "error_type": None if ok else outcome,
        "error": None if ok else outcome,
        "details": {
            "experiment_type": checker,
            "variant": variant,
            "target_url": target.url,
            "stages": stages,
            **details,
        },
    }


async def staged_https_probe(
    target: ExperimentTarget,
    *,
    checker: str,
    variant: str,
    sni: str | None,
    host_header: str,
    timeout_seconds: float,
) -> dict:
    total = time.monotonic()
    stages: list[dict] = []
    writer: asyncio.StreamWriter | None = None
    try:
        try:
            ips, elapsed = await _resolve(target.host, target.port, timeout_seconds)
            if not ips:
                raise RuntimeError("dns empty response")
            ip = ips[0]
            stages.append(_stage("dns", True, elapsed, "ok", ips=ips))
        except Exception as exc:
            outcome = _outcome(exc, "dns")
            stages.append(_stage("dns", False, _ms(total), outcome))
            return _row(target, checker, variant, False, outcome, total, stages, {
                "sni": sni, "host_header": host_header,
            })

        started = time.monotonic()
        try:
            _, plain_writer = await asyncio.wait_for(
                asyncio.open_connection(ip, target.port), timeout=timeout_seconds
            )
            stages.append(_stage("tcp_connect", True, _ms(started), "ok", connected_ip=ip))
            plain_writer.close()
            await plain_writer.wait_closed()
        except Exception as exc:
            outcome = _outcome(exc, "tcp")
            stages.append(_stage("tcp_connect", False, _ms(started), outcome, connected_ip=ip))
            return _row(target, checker, variant, False, outcome, total, stages, {
                "resolved_ip": ip, "sni": sni, "host_header": host_header,
            })

        started = time.monotonic()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    ip, target.port, ssl=_ssl_context(), server_hostname=sni
                ),
                timeout=timeout_seconds,
            )
            if writer is None:
                raise RuntimeError("open_connection returned no writer")
            ssl_obj = writer.get_extra_info("ssl_object")
            stages.append(_stage(
                "tls_handshake", True, _ms(started), "ok",
                tls_version=ssl_obj.version() if ssl_obj else None,
                cipher=ssl_obj.cipher()[0] if ssl_obj and ssl_obj.cipher() else None,
                alpn=ssl_obj.selected_alpn_protocol() if ssl_obj else None,
            ))
        except Exception as exc:
            outcome = _outcome(exc, "tls")
            stages.append(_stage("tls_handshake", False, _ms(started), outcome, connected_ip=ip))
            return _row(target, checker, variant, False, outcome, total, stages, {
                "resolved_ip": ip, "sni": sni, "host_header": host_header,
            })

        started = time.monotonic()
        try:
            request = (
                f"GET {target.path} HTTP/1.1\r\n"
                f"Host: {host_header}\r\n"
                "User-Agent: rknmon-experiment/0.1\r\n"
                "Connection: close\r\n\r\n"
            ).encode()
            writer.write(request)
            await asyncio.wait_for(writer.drain(), timeout=timeout_seconds)
            first = await asyncio.wait_for(reader.read(1), timeout=timeout_seconds)
            if not first:
                raise ConnectionError("empty response")
            stages.append(_stage("http_first_byte", True, _ms(started), "ok"))
            response = first + await asyncio.wait_for(reader.read(8191), timeout=timeout_seconds)
            status = _http_status(response)
            stages.append(_stage("http_total", True, _ms(started), "ok", http_status=status))
            return _row(target, checker, variant, True, "ok", total, stages, {
                "resolved_ip": ip,
                "sni": sni,
                "host_header": host_header,
                "http_status": status,
                "response_prefix_sha256": hashlib.sha256(response).hexdigest()[:16],
            })
        except Exception as exc:
            outcome = _outcome(exc, "http")
            stages.append(_stage("http_first_byte", False, _ms(started), outcome))
            return _row(target, checker, variant, False, outcome, total, stages, {
                "resolved_ip": ip, "sni": sni, "host_header": host_header,
            })
    finally:
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass


def _http_status(response: bytes) -> int | None:
    try:
        fields = response.split(b"\r\n", 1)[0].decode("ascii", errors="replace").split()
        return int(fields[1]) if len(fields) > 1 and fields[1].isdigit() else None
    except Exception:
        return None


class _UdpEcho(asyncio.DatagramProtocol):
    def __init__(self, payload: bytes):
        self.payload = payload
        self.response = asyncio.get_running_loop().create_future()

    def connection_made(self, transport):
        transport.sendto(self.payload)

    def datagram_received(self, data, addr):
        if not self.response.done():
            self.response.set_result((data, addr))

    def error_received(self, exc):
        if not self.response.done():
            self.response.set_exception(exc)


async def probe_udp_echo(spec: str, timeout: float) -> dict:
    name, value = (spec.split("=", 1) if "=" in spec else (spec, spec))
    host, port_s = value.rsplit(":", 1)
    port = int(port_s)
    started = time.monotonic()
    transport = None
    try:
        ips, dns_ms = await _resolve(host, port, timeout)
        token = f"rknmon-{uuid.uuid4()}".encode()
        protocol = _UdpEcho(token)
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: protocol, remote_addr=(ips[0], port)
        )
        data, addr = await asyncio.wait_for(protocol.response, timeout=timeout)
        ok = data == token
        outcome = "ok" if ok else "udp_payload_mismatch"
        return {
            "checker": "udp-echo", "target": name, "method": "controlled_echo",
            "ok": ok, "latency_ms": _ms(started), "http_status": None,
            "error_type": None if ok else outcome, "error": None if ok else outcome,
            "details": {
                "experiment_type": "udp-echo", "resolved_ip": ips[0], "port": port,
                "dns_duration_ms": dns_ms, "bytes_sent": len(token),
                "bytes_received": len(data), "peer": f"{addr[0]}:{addr[1]}",
            },
        }
    except Exception as exc:
        outcome = _outcome(exc, "udp")
        return {
            "checker": "udp-echo", "target": name, "method": "controlled_echo",
            "ok": False, "latency_ms": _ms(started), "http_status": None,
            "error_type": outcome, "error": str(exc)[:300] or outcome,
            "details": {"experiment_type": "udp-echo", "host": host, "port": port},
        }
    finally:
        if transport is not None:
            transport.close()


def _curl_error(code: int | None) -> str:
    if code is None:
        return "curl_failed"
    return {
        5: "proxy_dns_failed", 6: "dns_failed", 7: "tcp_connect_failed",
        28: "timeout", 35: "tls_handshake_failed", 55: "send_failed",
        56: "receive_failed", 92: "http3_error",
    }.get(code, "curl_failed")


async def probe_http3(url: str, timeout: float) -> dict:
    started = time.monotonic()
    curl = shutil.which("curl")
    if not curl:
        return {
            "checker": "http3", "target": url, "method": "curl_http3_only",
            "ok": False, "latency_ms": _ms(started), "http_status": None,
            "error_type": "curl_missing", "error": "curl_missing",
            "details": {"experiment_type": "http3"},
        }
    proc = await asyncio.create_subprocess_exec(
        curl, "--silent", "--show-error", "--http3-only", "--max-time", str(timeout),
        "--output", os.devnull, "--write-out", "%{http_code} %{time_total}", url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    fields = stdout.decode(errors="replace").split()
    status = int(fields[0]) if fields and fields[0].isdigit() else None
    ok = proc.returncode == 0 and status is not None and 200 <= status < 500
    outcome = None if ok else _curl_error(proc.returncode)
    return {
        "checker": "http3", "target": url, "method": "curl_http3_only",
        "ok": ok, "latency_ms": _ms(started), "http_status": status,
        "error_type": outcome,
        "error": None if ok else (stderr.decode(errors="replace").strip()[:300] or outcome),
        "details": {"experiment_type": "http3", "curl_exit_code": proc.returncode},
    }


def infer_mechanisms(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        if row.get("checker") != "mechanism-inference":
            grouped.setdefault(str(row.get("target")), []).append(row)
    inferred: list[dict[str, Any]] = []
    for target, rows in grouped.items():
        candidates: list[tuple[str, float, list[str]]] = []
        dns_bad = [r for r in rows if r.get("checker") == "dns" and not r.get("ok")]
        if dns_bad:
            candidates.append(("dns_interference", 0.8, sorted({
                str(r.get("error_type") or "dns_failure") for r in dns_bad
            })))
        if any(
            r.get("checker") == "cidrwhitelist"
            and r.get("error_type") == "cidr_whitelist_suspected" for r in rows
        ):
            candidates.append(("allowlisting", 0.78, ["whitelisted_ok_regular_failed"]))
        tls = [r for r in rows if r.get("checker") == "tls-ab"]
        if any(r.get("method") == "correct" and not r.get("ok") for r in tls) and any(
            r.get("method") != "correct" and r.get("ok") for r in tls
        ):
            candidates.append(("sni_filter", 0.88, ["same_ip_control_variant_ok", "correct_sni_failed"]))
        host = [r for r in rows if r.get("checker") == "host-ab"]
        if any(r.get("method") == "correct" and not r.get("ok") for r in host) and any(
            r.get("method") != "correct" and r.get("ok") for r in host
        ):
            candidates.append(("http_host_filter", 0.88, ["same_tls_control_host_ok", "correct_host_failed"]))
        if any(r.get("checker") == "http3" and not r.get("ok") for r in rows):
            candidates.append(("quic_or_udp_interference", 0.45, ["http3_failed"]))
        if any(r.get("checker") == "udp-echo" and not r.get("ok") for r in rows):
            candidates.append(("udp_path_interference", 0.5, ["controlled_udp_echo_failed"]))
        if any(
            str(r.get("error_type") or "").endswith("_reset")
            or r.get("error_type") == "connection_reset" for r in rows
        ):
            candidates.append(("rst_or_tcp_interference", 0.55, ["reset_observed"]))
        for mechanism, confidence, evidence in candidates:
            inferred.append({
                "checker": "mechanism-inference", "target": target, "method": mechanism,
                "ok": False, "latency_ms": None, "http_status": None,
                "error_type": mechanism, "error": None,
                "details": {
                    "experiment_type": "mechanism-inference", "hypothesis": mechanism,
                    "confidence": confidence, "evidence": evidence,
                },
            })
    return inferred


async def run_experimental_probes(
    *,
    target_specs: list[str],
    sni_variants: list[str],
    host_variants: list[str],
    udp_targets: list[str],
    http3_targets: list[str],
    timeout_seconds: float,
    artifact_dir: str = "/var/lib/rknmon/artifacts",
    capture_on_anomaly: bool = False,
    trace_on_anomaly: bool = False,
) -> list[dict[str, Any]]:
    targets = [parse_experiment_target(item) for item in target_specs if item.strip()]
    collector = FailureArtifactCollector(
        base_dir=artifact_dir,
        capture_on_anomaly=capture_on_anomaly,
        trace_on_anomaly=trace_on_anomaly,
    )
    results: list[dict[str, Any]] = []
    for target in targets:
        for variant in (sni_variants or ["correct", "none", "bogus.invalid"]):
            sni = target.host if variant == "correct" else (None if variant == "none" else variant)
            results.append(await collector.run(
                experiment_id=str(uuid.uuid4()), host=target.host, port=target.port,
                probe=lambda t=target, v=variant, s=sni: staged_https_probe(
                    t, checker="tls-ab", variant=v, sni=s, host_header=t.host,
                    timeout_seconds=timeout_seconds,
                ),
            ))
        for variant in host_variants:
            host_header = target.host if variant == "correct" else variant
            results.append(await collector.run(
                experiment_id=str(uuid.uuid4()), host=target.host, port=target.port,
                probe=lambda t=target, v=variant, h=host_header: staged_https_probe(
                    t, checker="host-ab", variant=v, sni=t.host, host_header=h,
                    timeout_seconds=timeout_seconds,
                ),
            ))
    for spec in udp_targets:
        _, value = (spec.split("=", 1) if "=" in spec else (spec, spec))
        host, port_s = value.rsplit(":", 1)
        results.append(await collector.run(
            experiment_id=str(uuid.uuid4()), host=host, port=int(port_s),
            probe=lambda item=spec: probe_udp_echo(item, timeout_seconds),
        ))
    for url in http3_targets:
        parsed = urlparse(url)
        results.append(await collector.run(
            experiment_id=str(uuid.uuid4()), host=parsed.hostname or url,
            port=parsed.port or 443,
            probe=lambda item=url: probe_http3(item, timeout_seconds),
        ))
    return results
