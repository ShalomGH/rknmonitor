from fastapi import APIRouter, HTTPException
from rknmon.db import fetchrow, fetch, execute
from rknmon.models.schemas import Target

router = APIRouter(prefix="/targets", tags=["targets"])

@router.get("")
async def list_targets(active_only: bool = False):
    if active_only:
        rows = await fetch("SELECT * FROM targets WHERE is_active = true ORDER BY id")
    else:
        rows = await fetch("SELECT * FROM targets ORDER BY id")
    return [dict(r) for r in rows]

@router.get("/{target_id}")
async def get_target(target_id: int):
    row = await fetchrow("SELECT * FROM targets WHERE id = $1", target_id)
    if not row:
        raise HTTPException(status_code=404, detail="Target not found")
    return dict(row)

@router.post("")
async def create_target(target: Target):
    row = await fetchrow(
        """
        INSERT INTO targets (url, domain, ip, category, source, is_active)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (domain) DO UPDATE SET
            url = EXCLUDED.url,
            ip = COALESCE(EXCLUDED.ip, targets.ip),
            category = COALESCE(EXCLUDED.category, targets.category),
            updated_at = now()
        RETURNING *
        """,
        str(target.url), target.domain, target.ip, target.category,
        target.source, target.is_active,
    )
    return dict(row)

@router.patch("/{target_id}")
async def update_target(target_id: int, data: dict):
    # Naive patch: update provided fields
    allowed = {"url", "domain", "ip", "category", "source", "is_active"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        raise HTTPException(status_code=400, detail="No valid fields to update")
    sets = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
    values = list(fields.values())
    row = await fetchrow(
        f"UPDATE targets SET {sets}, updated_at = now() WHERE id = $1 RETURNING *",
        target_id, *values,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Target not found")
    return dict(row)

@router.delete("/{target_id}")
async def delete_target(target_id: int):
    result = await execute("DELETE FROM targets WHERE id = $1", target_id)
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Target not found")
    return {"deleted": True}
