from rknmon.db import get_pool

async def init_schema():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS targets (
                id SERIAL PRIMARY KEY,
                url TEXT NOT NULL,
                domain TEXT NOT NULL,
                ip INET,
                category TEXT,
                source TEXT DEFAULT 'manual',
                is_active BOOLEAN DEFAULT true,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now(),
                CONSTRAINT uq_target_domain UNIQUE (domain)
            )
            """
        )
        await conn.execute(
            """
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
            )
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_probes_target_id ON probes(target_id)
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_probes_checked_at ON probes(checked_at)
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id BIGSERIAL PRIMARY KEY,
                target_id INTEGER REFERENCES targets(id) ON DELETE CASCADE,
                event_type VARCHAR(30) NOT NULL,
                old_state VARCHAR(10),
                new_state VARCHAR(10),
                details JSONB,
                created_at TIMESTAMPTZ DEFAULT now()
            )
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_events_target_id ON events(target_id)
            """
        )
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at)
            """
        )
