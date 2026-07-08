from __future__ import annotations

import asyncio
import logging
import random
from typing import List

from rknmon.config.settings import settings
from rknmon.custom_metrics import record_probe_latency, record_probe_result, set_active_targets
from rknmon.db import execute, fetchrow
from rknmon.probes.dns_probe import probe_dns
from rknmon.probes.evaluator import evaluate_targets
from rknmon.probes.http_probe import probe_http

logger = logging.getLogger(__name__)
CONCURRENCY = settings.probe_concurrency
CENTRAL_NODE_NAME = "central-control"


async def _central_probe_node_id() -> int:
    """Return an internal control node for scheduler-originated probes."""
    row = await fetchrow(
        """
        INSERT INTO probe_nodes (name, api_key, location, provider, role, last_seen_at, is_active)
        VALUES ($1, NULL, 'central', 'central', 'control', now(), true)
        ON CONFLICT (name) DO UPDATE SET
            role = 'control',
            last_seen_at = now(),
            is_active = true
        RETURNING id
        """,
        CENTRAL_NODE_NAME,
    )
    if not row:
        raise RuntimeError("failed to create or resolve central control probe node")
    return int(row["id"])


async def run_probe_for_target(
    target: dict,
    semaphore: asyncio.Semaphore,
    probe_node_id: int,
) -> None:
    async with semaphore:
        url = target["url"]
        domain = target["domain"]
        target_id = target["id"]

        http_result = await probe_http(url)
        await execute(
            """
            INSERT INTO probes (
                target_id, probe_node_id, probe_type, status_code,
                response_time_ms, body_hash, error, result
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            target_id,
            probe_node_id,
            "http",
            http_result.get("status_code"),
            http_result.get("response_time_ms"),
            http_result.get("body_hash"),
            http_result.get("error"),
            http_result,
        )
        rt = http_result.get("response_time_ms")
        if rt is not None:
            record_probe_latency(target_id, domain, "http", rt)
        record_probe_result(
            agent=CENTRAL_NODE_NAME,
            target_id=str(target_id),
            domain=domain,
            probe_type="http",
            status_code=http_result.get("status_code"),
            error=http_result.get("error"),
            result=http_result,
            response_time_ms=rt,
        )

        dns_result = await probe_dns(domain)
        resolver_err = next(
            (r["error"] for r in dns_result.get("results", []) if r.get("error")),
            None,
        )
        await execute(
            """
            INSERT INTO probes (
                target_id, probe_node_id, probe_type, response_time_ms,
                error, resolver, result
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            target_id,
            probe_node_id,
            "dns",
            dns_result.get("response_time_ms"),
            resolver_err,
            "multi",
            dns_result,
        )
        dns_rt = dns_result.get("response_time_ms")
        if dns_rt is not None:
            record_probe_latency(target_id, domain, "dns", dns_rt)
        record_probe_result(
            agent=CENTRAL_NODE_NAME,
            target_id=str(target_id),
            domain=domain,
            probe_type="dns",
            status_code=None,
            error=resolver_err,
            result=dns_result,
            response_time_ms=dns_rt,
        )


async def run_all(targets: List[dict]) -> None:
    set_active_targets(len(targets))
    semaphore = asyncio.Semaphore(CONCURRENCY)
    await asyncio.sleep(random.uniform(0, settings.probe_jitter_seconds))
    probe_node_id = await _central_probe_node_id()
    tasks = [run_probe_for_target(t, semaphore, probe_node_id) for t in targets]
    await asyncio.gather(*tasks, return_exceptions=True)
    await evaluate_targets([int(target["id"]) for target in targets])
