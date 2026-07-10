from __future__ import annotations

import asyncio

from rknmon.agent.dns_diagnostics import probe_dns_interference
from rknmon.agent.dpi import parse_target_list, probe_cidrwhitelist, probe_l4_25
from rknmon.agent.experiments import run_experimental_probes
from rknmon.agent.inference import infer_mechanisms


async def run_dpi_probe_cycle(
    client,
    target_specs: list[str],
    whitelisted_urls: list[str],
    regular_urls: list[str],
    timeout_seconds: float = 10.0,
    l4_payload_bytes: int = 65536,
    *,
    experiments_enabled: bool = False,
    experiment_targets: list[str] | None = None,
    sni_variants: list[str] | None = None,
    host_variants: list[str] | None = None,
    udp_targets: list[str] | None = None,
    http3_targets: list[str] | None = None,
    artifact_dir: str = "/var/lib/rknmon/artifacts",
    capture_on_anomaly: bool = False,
    trace_on_anomaly: bool = False,
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

    if experiments_enabled:
        results.extend(
            await run_experimental_probes(
                target_specs=experiment_targets or [],
                sni_variants=sni_variants or [],
                host_variants=host_variants or [],
                udp_targets=udp_targets or [],
                http3_targets=http3_targets or [],
                timeout_seconds=timeout_seconds,
                artifact_dir=artifact_dir,
                capture_on_anomaly=capture_on_anomaly,
                trace_on_anomaly=trace_on_anomaly,
            )
        )

    results.extend(infer_mechanisms(results))
    return await client.submit_dpi_results(results)
