"""Single-use invite tokens for one-command agent install.

The owner (admin) creates an invite via the admin CLI / endpoint, then
hands the token to a friend. The friend's install script bootstraps over
HTTPS, exchanges the invite for a permanent `NODE_API_KEY`, writes the
local `.env.agent` / `.env.xray`, and brings the agent stack up via
docker compose.

A token can be:
- single-use (default) or `max_uses > 1`
- pre-loaded with Xray subscription URLs and safe display names
- pre-bound to `name` / `location` / `provider`
- configured to enable DPI-only / DPI+Xray / Xray-only modes
- expired (default 7 days)

The bootstrap endpoint:
- validates the token
- mints a random 32-byte hex `node_api_key`
- inserts / updates a row in `probe_nodes` with that key
- returns enough config to drop into a `.env.agent` on the agent side
- NEVER echoes subscription URLs back over the wire to the agent — those
  stay on the central; the agent only receives a runtime config that
  points at central endpoints. (Subscription URLs are written to the
  agent's `.env.xray` by the installer running on the agent itself when
  the owner pre-bakes them into the install command.)
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg

from rknmon.config.settings import settings
from rknmon.db import fetch, fetchrow
from rknmon.models.schemas import (
    AgentBootstrapOut,
    AgentInviteCreateIn,
    AgentInviteOut,
)


TOKEN_BYTES = 24  # -> 48 hex chars, URL-safe
VALID_MODES = {"dpi", "xray"}


def generate_token() -> str:
    return secrets.token_hex(TOKEN_BYTES)


def generate_node_api_key() -> str:
    return "rnk_" + secrets.token_urlsafe(32)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_invite(row: asyncpg.Record | dict) -> AgentInviteOut:
    data = dict(row)
    if isinstance(data.get("expires_at"), datetime) and data["expires_at"].tzinfo is None:
        data["expires_at"] = data["expires_at"].replace(tzinfo=timezone.utc)
    if isinstance(data.get("created_at"), datetime) and data["created_at"].tzinfo is None:
        data["created_at"] = data["created_at"].replace(tzinfo=timezone.utc)
    return AgentInviteOut(**data)


def validate_modes(modes: list[str]) -> list[str]:
    if not modes:
        return ["dpi"]
    cleaned = [m.strip().lower() for m in modes if m and m.strip()]
    if not cleaned:
        return ["dpi"]
    unknown = [m for m in cleaned if m not in VALID_MODES]
    if unknown:
        raise ValueError(
            f"Unknown mode(s): {', '.join(unknown)}. Allowed: {sorted(VALID_MODES)}"
        )
    return cleaned


def validate_subscription_pairs(
    urls: list[str], names: list[str]
) -> tuple[list[str], list[str]]:
    urls = [u.strip() for u in urls if u and u.strip()]
    names = [n.strip() for n in names if n and n.strip()]
    if len(urls) != len(names):
        raise ValueError(
            f"XRAY_SUBSCRIPTION_URLS ({len(urls)}) and XRAY_SUBSCRIPTION_NAMES "
            f"({len(names)}) must have the same length"
        )
    if len(urls) > 32:
        raise ValueError("Too many subscriptions (max 32 per invite)")
    return urls, names


async def create_invite(payload: AgentInviteCreateIn) -> AgentInviteOut:
    """Insert a new invite row. Returns the freshly created record with token."""
    if not payload.name or not payload.name.strip():
        raise ValueError("name is required")
    if payload.max_uses < 1 or payload.max_uses > 1000:
        raise ValueError("max_uses must be between 1 and 1000")
    if payload.expires_in_hours < 1 or payload.expires_in_hours > 24 * 365:
        raise ValueError("expires_in_hours must be between 1 and 8760")
    modes = validate_modes(payload.modes)
    urls, names = validate_subscription_pairs(
        payload.xray_subscription_urls, payload.xray_subscription_names
    )
    if "xray" in modes and not urls:
        # xray mode without subscriptions is allowed (probe-only via local Xray)
        pass
    token = generate_token()
    expires_at = _utcnow() + timedelta(hours=payload.expires_in_hours)
    row = await fetchrow(
        """
        INSERT INTO agent_invites (
            token, name, location, provider, modes,
            xray_subscription_urls, xray_subscription_names, xray_test_url,
            expires_at, max_uses, note, created_by
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        RETURNING id, token, name, location, provider, modes,
                  xray_subscription_urls, xray_subscription_names, xray_test_url,
                  expires_at, max_uses, uses, note, created_by, created_at
        """,
        token,
        payload.name.strip(),
        payload.location,
        payload.provider,
        modes,
        urls,
        names,
        payload.xray_test_url,
        expires_at,
        payload.max_uses,
        payload.note,
        payload.created_by,
    )
    return _row_to_invite(row)


async def list_invites(active_only: bool = True) -> list[AgentInviteOut]:
    if active_only:
        rows = await fetch(
            """
            SELECT id, token, name, location, provider, modes,
                   xray_subscription_urls, xray_subscription_names, xray_test_url,
                   expires_at, max_uses, uses, note, created_by, created_at
            FROM agent_invites
            WHERE consumed_at IS NULL
              AND uses < max_uses
              AND expires_at > now()
            ORDER BY id DESC
            """
        )
    else:
        rows = await fetch(
            """
            SELECT id, token, name, location, provider, modes,
                   xray_subscription_urls, xray_subscription_names, xray_test_url,
                   expires_at, max_uses, uses, note, created_by, created_at
            FROM agent_invites
            ORDER BY id DESC
            """
        )
    return [_row_to_invite(r) for r in rows]


async def revoke_invite(invite_id: int) -> bool:
    row = await fetchrow(
        "DELETE FROM agent_invites WHERE id = $1 AND consumed_at IS NULL AND uses = 0 RETURNING id",
        invite_id,
    )
    return bool(row)


async def _load_valid_invite(token: str) -> Optional[asyncpg.Record]:
    row = await fetchrow(
        """
        SELECT id, name, location, provider, modes,
               xray_subscription_urls, xray_subscription_names, xray_test_url,
               expires_at, max_uses, uses
        FROM agent_invites
        WHERE token = $1
        FOR UPDATE
        """,
        token,
    )
    if not row:
        return None
    expires_at: datetime = row["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < _utcnow():
        return None
    if row["uses"] >= row["max_uses"]:
        return None
    return row


async def bootstrap_agent(
    token: str,
    name: str,
    location: Optional[str],
    provider: Optional[str],
    public_ip: Optional[str],
    agent_version: Optional[str],
) -> tuple[AgentBootstrapOut, dict]:
    """Validate invite, mint a permanent NODE_API_KEY, register a probe node.

    Returns the bootstrap response and the invite row that was consumed.
    """
    invite = await _load_valid_invite(token)
    if not invite:
        raise PermissionError("Invalid, expired, or fully used invite token")

    # Pre-baked location / provider from the invite win over the installer's
    # ad-hoc values, so the friend can't accidentally mis-attribute the node.
    final_name = (invite["name"] or name).strip()
    final_location = invite["location"] or location
    final_provider = invite["provider"] or provider

    api_key = generate_node_api_key()

    async def _txn(conn: asyncpg.Connection) -> int:
        # Insert / update probe node with the freshly minted api_key.
        await conn.execute(
            """
            INSERT INTO probe_nodes (name, api_key, location, provider,
                                     last_seen_at, last_ip, agent_version, is_active)
            VALUES ($1, $2, $3, $4, now(), $5, $6, true)
            ON CONFLICT (name) DO UPDATE SET
                api_key = EXCLUDED.api_key,
                location = EXCLUDED.location,
                provider = EXCLUDED.provider,
                last_seen_at = now(),
                last_ip = COALESCE(EXCLUDED.last_ip, probe_nodes.last_ip),
                agent_version = COALESCE(EXCLUDED.agent_version, probe_nodes.agent_version),
                is_active = true
            """,
            final_name,
            api_key,
            final_location,
            final_provider,
            public_ip,
            agent_version,
        )
        node_id = await conn.fetchval(
            "SELECT id FROM probe_nodes WHERE name = $1", final_name
        )
        # Consume the invite atomically.
        consumed = await conn.fetchval(
            """
            UPDATE agent_invites
            SET uses = uses + 1,
                consumed_at = COALESCE(consumed_at, now()),
                consumed_by_node_id = $2
            WHERE id = $1 AND uses < max_uses
            RETURNING id
            """,
            invite["id"],
            node_id,
        )
        if not consumed:
            raise PermissionError("Invite was consumed concurrently")
        return int(node_id)

    from rknmon.db import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _txn(conn)

    interval = int(getattr(settings, "probe_interval_seconds", 300) or 300)
    install_url = f"{settings.public_base_url.rstrip('/')}/install-agent.sh"

    out = AgentBootstrapOut(
        central_api_url=settings.public_base_url.rstrip("/"),
        node_api_key=api_key,
        agent_name=final_name,
        agent_location=final_location,
        agent_provider=final_provider,
        probe_interval_seconds=interval,
        modes=list(invite["modes"] or []),
        xray_subscription_urls=list(invite["xray_subscription_urls"] or []),
        xray_subscription_names=list(invite["xray_subscription_names"] or []),
        xray_test_url=invite["xray_test_url"] or "https://cp.cloudflare.com/",
        xray_socks_start_port=int(getattr(settings, "xray_socks_start_port", 11001)),
        install_docker_compose_url=install_url,
    )
    return out, dict(invite)
