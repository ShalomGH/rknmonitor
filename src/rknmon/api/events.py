from fastapi import APIRouter
from rknmon.db import fetch

router = APIRouter(prefix="/events", tags=["events"])

@router.get("")
async def list_events(target_id: int | None = None, limit: int = 100):
    if target_id:
        rows = await fetch(
            "SELECT * FROM events WHERE target_id = $1 ORDER BY created_at DESC LIMIT $2",
            target_id, limit,
        )
    else:
        rows = await fetch(
            "SELECT * FROM events ORDER BY created_at DESC LIMIT $1", limit
        )
    return [dict(r) for r in rows]
