from __future__ import annotations
import logging
from typing import List, Dict
from rknmon.db import fetch, execute
from rknmon.probes.classifier import classify, State
from rknmon.probes.state_engine import update_target_state
from rknmon.alerts.webhook import batch_send

logger = logging.getLogger(__name__)

async def evaluate_targets(target_ids: List[int] | None = None) -> List[dict]:
    """
    Fetch latest probe results, classify, update state, emit events & alerts.
    If target_ids is None, evaluates all targets.
    Returns list of emitted events.
    """
    if target_ids:
        # fetch latest http + dns probe per target
        where = "WHERE t.id = any($1)"
        params = (target_ids,)
    else:
        where = ""
        params = ()

    query = f"""
    SELECT
        t.id,
        t.domain,
        (SELECT result FROM probes
         WHERE target_id = t.id AND probe_type = 'http'
         ORDER BY checked_at DESC LIMIT 1) AS http_result,
        (SELECT result FROM probes
         WHERE target_id = t.id AND probe_type = 'dns'
         ORDER BY checked_at DESC LIMIT 1) AS dns_result
    FROM targets t
    {where}
    """

    rows = await fetch(query, *params)
    events: List[dict] = []

    for row in rows:
        http_result = row.get("http_result")
        dns_result = row.get("dns_result")
        state, details = classify(http_result, dns_result)
        event = await update_target_state(row["id"], state, details)
        if event:
            events.append(event)

    if events:
        await batch_send(events)

    logger.info(f"Evaluated {len(rows)} targets, {len(events)} state changes")
    return events
