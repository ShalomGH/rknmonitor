from __future__ import annotations
import logging
from rknmon.db import fetchrow, execute
from rknmon.probes.classifier import State
from rknmon.custom_metrics import record_event, update_target_state_metrics

logger = logging.getLogger(__name__)

async def _update_state_counts():
    from rknmon.db import fetch
    rows = await fetch("SELECT state, COUNT(*) AS n FROM targets GROUP BY state")
    update_target_state_metrics({r["state"]: r["n"] for r in rows})

async def update_target_state(
    target_id: int,
    new_state: State,
    details: dict,
) -> dict | None:
    """
    Persist classification result, emit event if state changed.
    Returns the created event dict or None if no change.
    """
    row = await fetchrow(
        "SELECT state FROM targets WHERE id = $1",
        target_id,
    )
    old_state: str | None = row["state"] if row else None

    await execute(
        "UPDATE targets SET state = $1, updated_at = now() WHERE id = $2",
        new_state, target_id,
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
        target_id, event_type, old_state, new_state, details,
    )
    logger.info(f"Target {target_id}: {old_state} -> {new_state} ({event_type})")
    record_event(event_type)
    await _update_state_counts()
    return dict(event) if event else None
