from fastapi import APIRouter, Request
from rknmon.db import fetch, fetchrow
from rknmon.api.deps import limiter

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("")
@limiter.limit("100/minute")
async def get_stats(request: Request):
    targets_total = await fetchrow("SELECT COUNT(*) AS n FROM targets")
    targets_active = await fetchrow(
        "SELECT COUNT(*) AS n FROM targets WHERE is_active = true"
    )
    by_state = await fetch(
        "SELECT state, COUNT(*) AS n FROM targets GROUP BY state"
    )
    by_category = await fetch(
        "SELECT category, COUNT(*) AS n FROM targets WHERE category IS NOT NULL GROUP BY category"
    )
    probes_24h = await fetchrow(
        """
        SELECT COUNT(*) AS n FROM probes
        WHERE checked_at > now() - interval '24 hours'
        """
    )
    events_24h = await fetchrow(
        """
        SELECT COUNT(*) AS n FROM events
        WHERE created_at > now() - interval '24 hours'
        """
    )
    latest_block = await fetchrow(
        """
        SELECT e.*, t.domain FROM events e
        JOIN targets t ON t.id = e.target_id
        WHERE e.event_type = 'target_blocked'
        ORDER BY e.created_at DESC LIMIT 1
        """
    )
    return {
        "targets": {
            "total": targets_total["n"] if targets_total else 0,
            "active": targets_active["n"] if targets_active else 0,
            "by_state": {r["state"]: r["n"] for r in by_state},
            "by_category": {r["category"]: r["n"] for r in by_category},
        },
        "probes_24h": probes_24h["n"] if probes_24h else 0,
        "events_24h": events_24h["n"] if events_24h else 0,
        "latest_block": dict(latest_block) if latest_block else None,
    }
