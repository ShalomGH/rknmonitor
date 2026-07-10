from __future__ import annotations

from typing import Any


def _dns_candidate(rows: list[dict[str, Any]]) -> tuple[str, float, list[str]] | None:
    failures = [row for row in rows if row.get("checker") == "dns" and not row.get("ok")]
    if not failures:
        return None

    strongest: tuple[float, list[str]] | None = None
    confidence_by_error = {
        "dns_block_ip": 0.92,
        "dns_mismatch_confirmed": 0.88,
        "dns_resolution_failure_confirmed": 0.82,
    }
    for row in failures:
        error_type = str(row.get("error_type") or "")
        confidence = confidence_by_error.get(error_type)
        if confidence is None:
            # A timeout, resolver exception or plain mismatch is a real failure,
            # but not enough to claim DNS interference.
            continue
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        evidence = [error_type]
        diagnosis = details.get("diagnosis")
        if diagnosis:
            evidence.append(str(diagnosis))
        if details.get("tcp_reference_reachable"):
            evidence.append("reference_ip_tcp_reachable")
        if details.get("tcp_system_reachable") is False and error_type == "dns_mismatch_confirmed":
            evidence.append("system_ip_tcp_unreachable")
        if int(details.get("reference_source_count") or 0) >= 2:
            evidence.append("multiple_reference_resolvers")
        candidate = (confidence, sorted(set(evidence)))
        if strongest is None or candidate[0] > strongest[0]:
            strongest = candidate

    if strongest is None:
        return None
    return "dns_interference", strongest[0], strongest[1]


def infer_mechanisms(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        if row.get("checker") != "mechanism-inference":
            grouped.setdefault(str(row.get("target")), []).append(row)

    inferred: list[dict[str, Any]] = []
    for target, rows in grouped.items():
        candidates: list[tuple[str, float, list[str]]] = []

        dns = _dns_candidate(rows)
        if dns is not None:
            candidates.append(dns)

        if any(
            row.get("checker") == "cidrwhitelist"
            and row.get("error_type") == "cidr_whitelist_suspected"
            for row in rows
        ):
            candidates.append(("allowlisting", 0.78, ["whitelisted_ok_regular_failed"]))

        tls = [row for row in rows if row.get("checker") == "tls-ab"]
        if any(row.get("method") == "correct" and not row.get("ok") for row in tls) and any(
            row.get("method") != "correct" and row.get("ok") for row in tls
        ):
            candidates.append(("sni_filter", 0.88, ["same_ip_control_variant_ok", "correct_sni_failed"]))

        host = [row for row in rows if row.get("checker") == "host-ab"]
        if any(row.get("method") == "correct" and not row.get("ok") for row in host) and any(
            row.get("method") != "correct" and row.get("ok") for row in host
        ):
            candidates.append(("http_host_filter", 0.88, ["same_tls_control_host_ok", "correct_host_failed"]))

        if any(row.get("checker") == "http3" and not row.get("ok") for row in rows):
            candidates.append(("quic_or_udp_interference", 0.45, ["http3_failed"]))

        if any(row.get("checker") == "udp-echo" and not row.get("ok") for row in rows):
            candidates.append(("udp_path_interference", 0.5, ["controlled_udp_echo_failed"]))

        if any(
            str(row.get("error_type") or "").endswith("_reset")
            or row.get("error_type") == "connection_reset"
            for row in rows
        ):
            candidates.append(("rst_or_tcp_interference", 0.55, ["reset_observed"]))

        for mechanism, confidence, evidence in candidates:
            inferred.append(
                {
                    "checker": "mechanism-inference",
                    "target": target,
                    "method": mechanism,
                    # A hypothesis row is derived evidence, not a failed network check.
                    "ok": True,
                    "latency_ms": None,
                    "http_status": None,
                    "error_type": None,
                    "error": None,
                    "details": {
                        "experiment_type": "mechanism-inference",
                        "hypothesis": mechanism,
                        "confidence": confidence,
                        "evidence": evidence,
                    },
                }
            )
    return inferred
