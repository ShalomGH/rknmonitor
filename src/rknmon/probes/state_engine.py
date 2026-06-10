from __future__ import annotations
import json
import logging
from rknmon.db import fetchrow, execute
from rknmon.probes.classifier import State
from rknmon.custom_metrics import ensure_event_metric, record_event, update_target_state_metrics

logger = logging.getLogger(__name__)


async def _update_state_counts():
    from rknmon.db import fetch
    rows = await fetch("SELECT state, COUNT(*) AS n FROM target_states GROUP BY state")
    update_target_state_metrics({r["state"]: r["n"] for r in rows})


async def refresh_target_state_metrics():
    await _update_state_counts()


async def refresh_event_metric_labels():
    from rknmon.db import fetch
    rows = await fetch("SELECT DISTINCT event_type FROM events")
    for row in rows:
        ensure_event_metric(row["event_type"])


async def update_target_state(
    target_id: int,
    probe_node_id: int,
    new_state: State,
    details: dict,
) -> dict | None:
    row = await fetchrow(
        "SELECT state FROM target_states WHERE target_id = $1 AND probe_node_id = $2",
        target_id,
        probe_node_id,
    )
    old_state: str | None = row["state"] if row else None

    await execute(
        """
        INSERT INTO target_states (target_id, probe_node_id, state, details, updated_at)
        VALUES ($1, $2, $3, $4, now())
        ON CONFLICT (target_id, probe_node_id)
        DO UPDATE SET state = EXCLUDED.state, details = EXCLUDED.details, updated_at = now()
        """,
        target_id,
        probe_node_id,
        new_state,
        json.dumps(details),
    )

    if old_state == new_state:
        return None

    event_type = "state_changed"
    if new_state == "blocked":
        event_type = "target_blocked"
    elif new_state == "clear" and old_state == "blocked":
        event_type = "target_unblocked"

    event = await fetchrow(
        """
        INSERT INTO events (target_id, event_type, old_state, new_state, details)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING *
        """,
        target_id,
        event_type,
        old_state,
        new_state,
        json.dumps({"probe_node_id": probe_node_id, **details}),
    )
    logger.info(f"Target {target_id} on node {probe_node_id}: {old_state} -> {new_state} ({event_type})")
    record_event(event_type)
    await refresh_target_state_metrics()
    return dict(event) if event else None
