from __future__ import annotations
import json
import logging
from typing import List
from rknmon.db import fetch
from rknmon.probes.classifier import classify
from rknmon.probes.state_engine import update_target_state, refresh_event_metric_labels, refresh_target_state_metrics
from rknmon.alerts.webhook import batch_send

logger = logging.getLogger(__name__)


def _decode_jsonb(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


async def evaluate_targets(target_ids: List[int] | None = None) -> List[dict]:
    if target_ids is None:
        t_rows = await fetch("SELECT id, domain FROM targets WHERE is_active = true")
    else:
        t_rows = await fetch(
            "SELECT id, domain FROM targets WHERE is_active = true AND id = any($1)",
            target_ids,
        )

    if not t_rows:
        return []

    ids = [int(r["id"]) for r in t_rows]

    node_rows = await fetch(
        """
        SELECT DISTINCT probe_node_id
        FROM probes
        WHERE target_id = any($1) AND probe_node_id IS NOT NULL
        ORDER BY probe_node_id
        """,
        ids,
    )
    probe_node_ids = [int(r["probe_node_id"]) for r in node_rows]
    if not probe_node_ids:
        return []

    http_rows = await fetch(
        """
        SELECT DISTINCT ON (target_id, probe_node_id) target_id, probe_node_id, result
        FROM probes
        WHERE target_id = any($1) AND probe_node_id = any($2) AND probe_type = 'http'
        ORDER BY target_id, probe_node_id, checked_at DESC
        """,
        ids,
        probe_node_ids,
    )
    dns_rows = await fetch(
        """
        SELECT DISTINCT ON (target_id, probe_node_id) target_id, probe_node_id, result
        FROM probes
        WHERE target_id = any($1) AND probe_node_id = any($2) AND probe_type = 'dns'
        ORDER BY target_id, probe_node_id, checked_at DESC
        """,
        ids,
        probe_node_ids,
    )

    http_map = {
        (int(r["target_id"]), int(r["probe_node_id"])): _decode_jsonb(r["result"])
        for r in http_rows
    }
    dns_map = {
        (int(r["target_id"]), int(r["probe_node_id"])): _decode_jsonb(r["result"])
        for r in dns_rows
    }

    events: List[dict] = []
    for tid in ids:
        for probe_node_id in probe_node_ids:
            state, details = classify(
                http_map.get((tid, probe_node_id)),
                dns_map.get((tid, probe_node_id)),
            )
            event = await update_target_state(tid, probe_node_id, state, details)
            if event:
                events.append(event)

    if events:
        await batch_send(events)

    await refresh_target_state_metrics()
    await refresh_event_metric_labels()
    logger.info(f"Evaluated {len(ids)} targets across {len(probe_node_ids)} nodes, {len(events)} state changes")
    return events
