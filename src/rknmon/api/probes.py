from fastapi import APIRouter, Request
from rknmon.db import fetch
from rknmon.api.deps import limiter

router = APIRouter(prefix="/probes", tags=["probes"])

@router.get("/latest")
@limiter.limit("100/minute")
async def list_latest(request: Request, target_id: int | None = None, probe_node_id: int | None = None, limit: int = 100):
    if target_id and probe_node_id:
        rows = await fetch(
            """
            SELECT p.*, t.domain
            FROM probes p
            JOIN targets t ON t.id = p.target_id
            WHERE p.target_id = $1 AND p.probe_node_id = $2
            ORDER BY p.checked_at DESC
            LIMIT $3
            """,
            target_id, probe_node_id, limit,
        )
    elif target_id:
        rows = await fetch(
            """
            SELECT p.*, t.domain
            FROM probes p
            JOIN targets t ON t.id = p.target_id
            WHERE p.target_id = $1
            ORDER BY p.checked_at DESC
            LIMIT $2
            """,
            target_id, limit,
        )
    elif probe_node_id:
        rows = await fetch(
            """
            SELECT DISTINCT ON (target_id) p.*, t.domain
            FROM probes p
            JOIN targets t ON t.id = p.target_id
            WHERE p.probe_node_id = $1
            ORDER BY target_id, checked_at DESC
            """,
            probe_node_id,
        )
    else:
        rows = await fetch(
            """
            SELECT DISTINCT ON (target_id) p.*, t.domain
            FROM probes p
            JOIN targets t ON t.id = p.target_id
            ORDER BY target_id, checked_at DESC
            """
        )
    return [dict(r) for r in rows]

@router.get("/statistics")
@limiter.limit("100/minute")
async def probe_stats(request: Request):
    total = await fetch("SELECT COUNT(*) FROM probes")
    by_type = await fetch(
        "SELECT probe_type, COUNT(*) as count FROM probes GROUP BY probe_type"
    )
    recent_errors = await fetch(
        """
        SELECT COUNT(*) FROM probes
        WHERE error IS NOT NULL AND checked_at > now() - interval '24 hours'
        """
    )
    return {
        "total": total[0]["count"] if total else 0,
        "by_type": [dict(r) for r in by_type],
        "errors_24h": recent_errors[0]["count"] if recent_errors else 0,
    }
