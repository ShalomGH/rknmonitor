from fastapi import APIRouter, Request
from rknmon.db import fetch
from rknmon.api.deps import limiter

router = APIRouter(prefix="/events", tags=["events"])

@router.get("")
@limiter.limit("100/minute")
async def list_events(request: Request, target_id: int | None = None, limit: int = 100):
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
