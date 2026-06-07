from __future__ import annotations
import logging
from rknmon.db import execute
from rknmon.config.settings import settings

logger = logging.getLogger(__name__)

async def cleanup_old_records() -> dict:
    """
    Delete probes older than result_retention_days and events older than event_retention_days.
    Returns dict with count of deleted rows per table.
    """
    probes_deleted = await execute(
        "DELETE FROM probes WHERE checked_at < now() - ($1 || ' days')::interval",
        str(settings.result_retention_days),
    )
    events_deleted = await execute(
        "DELETE FROM events WHERE created_at < now() - ($1 || ' days')::interval",
        str(settings.event_retention_days),
    )
    # asyncpg возвращает строку вида "DELETE N"
    result = {
        "probes_deleted_rowcount": parse_rowcount(probes_deleted),
        "events_deleted_rowcount": parse_rowcount(events_deleted),
    }
    logger.info(
        f"Cleanup complete: {result['probes_deleted_rowcount']} probes, "
        f"{result['events_deleted_rowcount']} events deleted"
    )
    return result

def parse_rowcount(status: str) -> int:
    if status:
        parts = status.split()
        if parts:
            try:
                return int(parts[-1])
            except ValueError:
                return 0
    return 0
