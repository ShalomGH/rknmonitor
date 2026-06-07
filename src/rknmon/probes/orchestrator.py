from __future__ import annotations
import asyncio
import random
import logging
from typing import List
from rknmon.config.settings import settings
from rknmon.probes.http_probe import probe_http
from rknmon.probes.dns_probe import probe_dns
from rknmon.db import execute
from rknmon.custom_metrics import record_probe_latency, set_active_targets

logger = logging.getLogger(__name__)

CONCURRENCY = settings.probe_concurrency

async def run_probe_for_target(target: dict, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        url = target["url"]
        domain = target["domain"]
        target_id = target["id"]

        # HTTP probe
        http_result = await probe_http(url)
        await execute(
            """
            INSERT INTO probes (target_id, probe_type, status_code, response_time_ms, body_hash, error, result)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            target_id, "http", http_result.get("status_code"), http_result.get("response_time_ms"),
            http_result.get("body_hash"), http_result.get("error"), http_result
        )
        rt = http_result.get("response_time_ms")
        if rt is not None:
            record_probe_latency(target_id, domain, "http", rt)
        logger.debug(f"HTTP probe {domain}: {http_result.get('status_code')} in {rt}ms")

        # DNS probe
        dns_result = await probe_dns(domain)
        resolver_err = None
        for r in dns_result.get("results", []):
            if r.get("error"):
                resolver_err = r["error"]
                break
        await execute(
            """
            INSERT INTO probes (target_id, probe_type, error, resolver, result)
            VALUES ($1, $2, $3, $4, $5)
            """,
            target_id, "dns", resolver_err, "multi", dns_result
        )
        dns_rt = dns_result.get("response_time_ms")
        if dns_rt is not None:
            record_probe_latency(target_id, domain, "dns", dns_rt)
        logger.debug(f"DNS probe {domain}: tampered={dns_result.get('tampered')}")

async def run_all(targets: List[dict]) -> None:
    set_active_targets(len(targets))
    semaphore = asyncio.Semaphore(CONCURRENCY)
    jitter = settings.probe_jitter_seconds
    # add jitter so we don't thundering herd
    await asyncio.sleep(random.uniform(0, jitter))
    tasks = [run_probe_for_target(t, semaphore) for t in targets]
    await asyncio.gather(*tasks, return_exceptions=True)
