from __future__ import annotations
import logging
from typing import List
from rknmon.db import fetch, execute
from rknmon.probes.classifier import classify
from rknmon.probes.state_engine import update_target_state
from rknmon.alerts.webhook import batch_send

logger = logging.getLogger(__name__)

async def evaluate_targets(target_ids: List[int] | None = None) -> List[dict]:
    """
    Fetch latest probe results, classify, update state, emit events & alerts.
    If target_ids is None, evaluates all active targets.
    Uses batched queries (3 total) instead of N+1 correlated subqueries.
    Returns list of emitted events.
    """
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

    # Fetch latest http + dns results in two flat queries
    http_rows = await fetch(
        """
        SELECT DISTINCT ON (target_id) target_id, result
        FROM probes
        WHERE target_id = any($1) AND probe_type = 'http'
        ORDER BY target_id, checked_at DESC
        """,
        ids,
    )
    dns_rows = await fetch(
        """
        SELECT DISTINCT ON (target_id) target_id, result
        FROM probes
        WHERE target_id = any($1) AND probe_type = 'dns'
        ORDER BY target_id, checked_at DESC
        """,
        ids,
    )

    http_map = {int(r["target_id"]): r["result"] for r in http_rows}
    dns_map = {int(r["target_id"]): r["result"] for r in dns_rows}

    events: List[dict] = []
    for tid in ids:
        state, details = classify(http_map.get(tid), dns_map.get(tid))
        event = await update_target_state(tid, state, details)
        if event:
            events.append(event)

    if events:
        await batch_send(events)

    logger.info(f"Evaluated {len(ids)} targets, {len(events)} state changes")
    return events
