import logging
import asyncpg
from rknmon.db import get_pool

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS targets (
    id SERIAL PRIMARY KEY,
    url TEXT NOT NULL,
    domain TEXT NOT NULL,
    ip INET,
    category TEXT,
    source TEXT DEFAULT 'manual',
    is_active BOOLEAN DEFAULT true,
    state VARCHAR(10) DEFAULT 'clear',
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_target_domain UNIQUE (domain)
);

CREATE TABLE IF NOT EXISTS probes (
    id SERIAL PRIMARY KEY,
    target_id INTEGER REFERENCES targets(id) ON DELETE CASCADE,
    probe_type VARCHAR(10) NOT NULL,
    status_code INTEGER,
    response_time_ms INTEGER,
    body_hash TEXT,
    error TEXT,
    resolver TEXT,
    result JSONB,
    checked_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_probes_target_id ON probes(target_id);
CREATE INDEX IF NOT EXISTS idx_probes_checked_at ON probes(checked_at);

CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    target_id INTEGER REFERENCES targets(id) ON DELETE CASCADE,
    event_type VARCHAR(30) NOT NULL,
    old_state VARCHAR(10),
    new_state VARCHAR(10),
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_events_target_id ON events(target_id);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);
"""

async def init_schema() -> None:
    """Create tables/indexes if missing. Uses advisory lock #1 to avoid races between uvicorn workers."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        locked = await conn.fetchval("SELECT pg_try_advisory_lock(1)")
        if not locked:
            logger.info("Schema init already in progress by another process, skipping")
            return
        try:
            await conn.execute(SCHEMA_SQL)
            logger.info("Schema initialized")
        except asyncpg.exceptions.UniqueViolationError:
            logger.info("Race on index creation, ignoring")
        finally:
            await conn.execute("SELECT pg_advisory_unlock(1)")
