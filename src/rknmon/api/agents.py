import json
import os

from fastapi import APIRouter, HTTPException, Request

from rknmon.agent.config import AgentSettings
from rknmon.custom_metrics import record_dpi_probe, record_probe_latency, record_xray_probe
from rknmon.db import execute, fetch, fetchrow
from rknmon.models.schemas import (
    AgentHeartbeatIn,
    AgentProbeBatchIn,
    AgentRegisterIn,
    DpiProbeBatchIn,
    XrayProbeBatchIn,
)
from rknmon.probes.evaluator import evaluate_targets

router = APIRouter(prefix="/agent", tags=["agent"])


def _poll_interval_seconds() -> int:
    try:
        return AgentSettings().probe_interval_seconds
    except Exception:
        return int(os.getenv("PROBE_INTERVAL_SECONDS", "300"))


async def _get_probe_node(request: Request) -> dict:
    api_key = request.headers.get("X-Node-API-Key")
    if not api_key:
        raise HTTPException(status_code=403, detail="Forbidden: missing node API key")
    row = await fetchrow(
        "SELECT id, name, is_active FROM probe_nodes WHERE api_key = $1",
        api_key,
    )
    if not row or not row.get("is_active", False):
        raise HTTPException(status_code=403, detail="Forbidden: invalid node API key")
    return dict(row)


@router.post("/register")
async def agent_register(request: Request, payload: AgentRegisterIn):
    api_key = request.headers.get("X-Node-API-Key")
    if not api_key:
        raise HTTPException(status_code=403, detail="Forbidden: missing node API key")

    await fetchrow("SELECT id FROM probe_nodes WHERE api_key = $1", api_key)
    await execute(
        """
        INSERT INTO probe_nodes (name, api_key, location, provider, last_seen_at, last_ip, agent_version, is_active)
        VALUES ($1, $2, $3, $4, now(), $5, $6, true)
        ON CONFLICT (api_key) DO UPDATE SET
            name = EXCLUDED.name,
            location = EXCLUDED.location,
            provider = EXCLUDED.provider,
            last_seen_at = now(),
            last_ip = EXCLUDED.last_ip,
            agent_version = EXCLUDED.agent_version,
            is_active = true
        """,
        payload.name,
        api_key,
        payload.location,
        payload.provider,
        payload.public_ip,
        payload.agent_version,
    )
    row = await fetchrow("SELECT id, name, is_active FROM probe_nodes WHERE api_key = $1", api_key)
    if not row:
        raise HTTPException(status_code=500, detail="Probe node registration failed")
    return {
        "probe_node_id": row["id"],
        "name": row["name"],
        "is_active": row["is_active"],
        "poll_interval_seconds": _poll_interval_seconds(),
    }


@router.post("/heartbeat")
async def agent_heartbeat(request: Request, payload: AgentHeartbeatIn):
    node = await _get_probe_node(request)
    await execute(
        """
        UPDATE probe_nodes
        SET last_seen_at = now(),
            last_ip = COALESCE($2, last_ip),
            agent_version = COALESCE($3, agent_version)
        WHERE id = $1
        """,
        node["id"],
        payload.public_ip,
        payload.agent_version,
    )
    return {
        "probe_node_id": node["id"],
        "status": "ok",
        "poll_interval_seconds": _poll_interval_seconds(),
    }


@router.get("/targets")
async def agent_targets(request: Request):
    await _get_probe_node(request)
    rows = await fetch(
        "SELECT id, url, domain, category, is_active FROM targets WHERE is_active = true ORDER BY id"
    )
    return [dict(r) for r in rows]


@router.post("/results")
async def ingest_probe_batch(request: Request, payload: AgentProbeBatchIn):
    node = await _get_probe_node(request)
    target_rows = await fetch(
        "SELECT id, domain FROM targets WHERE id = any($1)",
        [probe.target_id for probe in payload.results],
    )
    target_domains = {int(r["id"]): r["domain"] for r in target_rows}

    touched_target_ids: set[int] = set()
    for probe in payload.results:
        touched_target_ids.add(probe.target_id)
        await execute(
            """
            INSERT INTO probes (target_id, probe_node_id, probe_type, status_code, response_time_ms, body_hash, error, resolver, result)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            probe.target_id,
            node["id"],
            probe.probe_type,
            probe.status_code,
            probe.response_time_ms,
            probe.body_hash,
            probe.error,
            probe.resolver,
            json.dumps(probe.result or {}),
        )
        if probe.response_time_ms is not None:
            domain = target_domains.get(probe.target_id, str(probe.target_id))
            record_probe_latency(str(probe.target_id), domain, probe.probe_type, probe.response_time_ms)

    await evaluate_targets(sorted(touched_target_ids))
    return {"accepted": len(payload.results), "probe_node_id": node["id"]}


@router.post("/xray-results")
async def ingest_xray_probe_batch(request: Request, payload: XrayProbeBatchIn):
    node = await _get_probe_node(request)
    for probe in payload.results:
        await execute(
            """
            INSERT INTO xray_probe_results (
                probe_node_id, profile_id, profile_name, subscription_name, protocol, transport, security,
                sni, fingerprint, server_host, server_port, socks_port, test_url, ok,
                latency_ms, http_status, bytes_downloaded, error_type, error
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19)
            """,
            node["id"],
            probe.profile_id,
            probe.profile_name,
            probe.subscription_name,
            probe.protocol,
            probe.transport,
            probe.security,
            probe.sni,
            probe.fingerprint,
            probe.server_host,
            probe.server_port,
            probe.socks_port,
            probe.test_url,
            probe.ok,
            probe.latency_ms,
            probe.http_status,
            probe.bytes_downloaded,
            probe.error_type,
            probe.error,
        )
        record_xray_probe(
            agent=node["name"],
            subscription=probe.subscription_name,
            profile=probe.profile_id,
            protocol=probe.protocol,
            transport=probe.transport,
            server=probe.server_host,
            ok=probe.ok,
            latency_ms=probe.latency_ms,
            error_type=probe.error_type,
        )
    return {"accepted": len(payload.results), "probe_node_id": node["id"]}


@router.post("/dpi-results")
async def ingest_dpi_probe_batch(request: Request, payload: DpiProbeBatchIn):
    node = await _get_probe_node(request)
    for probe in payload.results:
        await execute(
            """
            INSERT INTO dpi_probe_results (
                probe_node_id, checker, target, method, ok, latency_ms,
                http_status, error_type, error, details
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            node["id"],
            probe.checker,
            probe.target,
            probe.method,
            probe.ok,
            probe.latency_ms,
            probe.http_status,
            probe.error_type,
            probe.error,
            json.dumps(probe.details or {}),
        )
        record_dpi_probe(
            agent=node["name"],
            checker=probe.checker,
            target=probe.target,
            method=probe.method,
            ok=probe.ok,
            latency_ms=probe.latency_ms,
            error_type=probe.error_type,
        )
    return {"accepted": len(payload.results), "probe_node_id": node["id"]}
