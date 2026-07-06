import logging
import asyncpg
from rknmon.db import get_pool

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS probe_nodes (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    location TEXT,
    provider TEXT,
    api_key TEXT NOT NULL,
    last_seen_at TIMESTAMPTZ,
    last_ip TEXT,
    agent_version TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_probe_node_name UNIQUE (name),
    CONSTRAINT uq_probe_node_api_key UNIQUE (api_key)
);

ALTER TABLE probe_nodes ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ;
ALTER TABLE probe_nodes ADD COLUMN IF NOT EXISTS last_ip TEXT;
ALTER TABLE probe_nodes ADD COLUMN IF NOT EXISTS agent_version TEXT;

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
    probe_node_id INTEGER REFERENCES probe_nodes(id) ON DELETE CASCADE,
    probe_type VARCHAR(10) NOT NULL,
    status_code INTEGER,
    response_time_ms INTEGER,
    body_hash TEXT,
    error TEXT,
    resolver TEXT,
    result JSONB,
    checked_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE probes ADD COLUMN IF NOT EXISTS probe_node_id INTEGER REFERENCES probe_nodes(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_probes_target_id ON probes(target_id);
CREATE INDEX IF NOT EXISTS idx_probes_probe_node_id ON probes(probe_node_id);
CREATE INDEX IF NOT EXISTS idx_probes_checked_at ON probes(checked_at);

CREATE TABLE IF NOT EXISTS target_states (
    id BIGSERIAL PRIMARY KEY,
    target_id INTEGER REFERENCES targets(id) ON DELETE CASCADE,
    probe_node_id INTEGER REFERENCES probe_nodes(id) ON DELETE CASCADE,
    state VARCHAR(10) NOT NULL,
    details JSONB,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (target_id, probe_node_id)
);

ALTER TABLE target_states ADD COLUMN IF NOT EXISTS probe_node_id INTEGER REFERENCES probe_nodes(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_target_states_target_id ON target_states(target_id);
CREATE INDEX IF NOT EXISTS idx_target_states_probe_node_id ON target_states(probe_node_id);

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

CREATE TABLE IF NOT EXISTS xray_probe_results (
    id BIGSERIAL PRIMARY KEY,
    probe_node_id INTEGER REFERENCES probe_nodes(id) ON DELETE CASCADE,
    profile_id TEXT NOT NULL,
    profile_name TEXT NOT NULL,
    subscription_name TEXT DEFAULT 'default',
    protocol TEXT NOT NULL,
    transport TEXT,
    security TEXT,
    sni TEXT,
    fingerprint TEXT,
    server_host TEXT NOT NULL,
    server_port INTEGER NOT NULL,
    socks_port INTEGER,
    test_url TEXT NOT NULL,
    ok BOOLEAN NOT NULL,
    latency_ms DOUBLE PRECISION,
    http_status INTEGER,
    bytes_downloaded INTEGER,
    error_type TEXT,
    error TEXT,
    checked_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_xray_probe_results_node_checked ON xray_probe_results(probe_node_id, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_xray_probe_results_profile_checked ON xray_probe_results(profile_id, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_xray_probe_results_ok ON xray_probe_results(ok);
ALTER TABLE xray_probe_results ADD COLUMN IF NOT EXISTS subscription_name TEXT DEFAULT 'default';
CREATE INDEX IF NOT EXISTS idx_xray_probe_results_subscription_checked ON xray_probe_results(subscription_name, checked_at DESC);

CREATE TABLE IF NOT EXISTS dpi_probe_results (
    id BIGSERIAL PRIMARY KEY,
    probe_node_id INTEGER REFERENCES probe_nodes(id) ON DELETE CASCADE,
    checker TEXT NOT NULL,
    target TEXT NOT NULL,
    method TEXT NOT NULL,
    ok BOOLEAN NOT NULL,
    latency_ms DOUBLE PRECISION,
    http_status INTEGER,
    error_type TEXT,
    error TEXT,
    details JSONB,
    checked_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_dpi_probe_results_node_checked ON dpi_probe_results(probe_node_id, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_dpi_probe_results_checker_checked ON dpi_probe_results(checker, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_dpi_probe_results_target_checked ON dpi_probe_results(target, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_dpi_probe_results_ok ON dpi_probe_results(ok);

CREATE TABLE IF NOT EXISTS agent_invites (
    id SERIAL PRIMARY KEY,
    token TEXT NOT NULL,
    name TEXT NOT NULL,
    location TEXT,
    provider TEXT,
    modes TEXT[] NOT NULL DEFAULT ARRAY['dpi']::TEXT[],
    xray_subscription_urls TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    xray_subscription_names TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    xray_test_url TEXT DEFAULT 'https://cp.cloudflare.com/',
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    consumed_by_node_id INTEGER REFERENCES probe_nodes(id) ON DELETE SET NULL,
    max_uses INTEGER NOT NULL DEFAULT 1,
    uses INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_agent_invite_token UNIQUE (token)
);

CREATE INDEX IF NOT EXISTS idx_agent_invites_token ON agent_invites(token);
CREATE INDEX IF NOT EXISTS idx_agent_invites_expires_at ON agent_invites(expires_at);

ALTER TABLE agent_invites ADD COLUMN IF NOT EXISTS modes TEXT[] NOT NULL DEFAULT ARRAY['dpi']::TEXT[];
ALTER TABLE agent_invites ADD COLUMN IF NOT EXISTS xray_subscription_urls TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE agent_invites ADD COLUMN IF NOT EXISTS xray_subscription_names TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[];
ALTER TABLE agent_invites ADD COLUMN IF NOT EXISTS xray_test_url TEXT DEFAULT 'https://cp.cloudflare.com/';
ALTER TABLE agent_invites ADD COLUMN IF NOT EXISTS max_uses INTEGER NOT NULL DEFAULT 1;
ALTER TABLE agent_invites ADD COLUMN IF NOT EXISTS uses INTEGER NOT NULL DEFAULT 0;
ALTER TABLE agent_invites ADD COLUMN IF NOT EXISTS note TEXT;
ALTER TABLE agent_invites ADD COLUMN IF NOT EXISTS created_by TEXT;

CREATE TABLE IF NOT EXISTS xray_subscription_health (
    id BIGSERIAL PRIMARY KEY,
    probe_node_id INTEGER REFERENCES probe_nodes(id) ON DELETE CASCADE,
    subscription_name TEXT NOT NULL,
    subscription_url TEXT NOT NULL,
    ok BOOLEAN NOT NULL,
    http_status INTEGER,
    error_type TEXT,
    error TEXT,
    profiles_count INTEGER NOT NULL DEFAULT 0,
    checked_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_xray_subscription_health_node_checked
    ON xray_subscription_health(probe_node_id, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_xray_subscription_health_name_checked
    ON xray_subscription_health(subscription_name, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_xray_subscription_health_ok
    ON xray_subscription_health(ok);
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
