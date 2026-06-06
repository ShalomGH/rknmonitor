from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from rknmon.db import fetch
from rknmon.api.deps import limiter
import csv
import io

router = APIRouter(prefix="/export", tags=["export"])


@router.get("/targets")
@limiter.limit("30/minute")
async def export_targets(request: Request, format: str = Query("json", enum=["json", "csv"])):
    rows = await fetch(
        "SELECT id, url, domain, ip, category, source, is_active, state, created_at, updated_at FROM targets ORDER BY id"
    )
    data = [dict(r) for r in rows]
    if format == "json":
        return JSONResponse(content=data)

    buf = io.StringIO()
    if data:
        writer = csv.DictWriter(buf, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
    return PlainTextResponse(content=buf.getvalue(), media_type="text/csv")


@router.get("/events")
@limiter.limit("30/minute")
async def export_events(
    request: Request,
    format: str = Query("json", enum=["json", "csv"]),
    target_id: int | None = None,
    limit: int = Query(10000, le=100000),
):
    if target_id:
        rows = await fetch(
            """
            SELECT e.id, e.target_id, t.domain, e.event_type, e.old_state, e.new_state, e.details, e.created_at
            FROM events e JOIN targets t ON t.id = e.target_id
            WHERE e.target_id = $1
            ORDER BY e.created_at DESC
            LIMIT $2
            """,
            target_id,
            limit,
        )
    else:
        rows = await fetch(
            """
            SELECT e.id, e.target_id, t.domain, e.event_type, e.old_state, e.new_state, e.details, e.created_at
            FROM events e JOIN targets t ON t.id = e.target_id
            ORDER BY e.created_at DESC
            LIMIT $1
            """,
            limit,
        )
    data = [dict(r) for r in rows]
    if format == "json":
        return JSONResponse(content=data)

    buf = io.StringIO()
    if data:
        writer = csv.DictWriter(buf, fieldnames=data[0].keys())
        writer.writeheader()
        for row in data:
            # JSONB details -> str for CSV
            row["details"] = str(row.get("details") or "")
            writer.writerow(row)
    return PlainTextResponse(content=buf.getvalue(), media_type="text/csv")
