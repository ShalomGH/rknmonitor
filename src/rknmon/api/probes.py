from fastapi import APIRouter
from rknmon.db import fetch

router = APIRouter(prefix="/probes", tags=["probes"])

@router.get("/latest")
async def list_latest(target_id: int | None = None, limit: int = 100):
    if target_id:
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
async def probe_stats():
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
