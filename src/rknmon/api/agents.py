import json
import os

from fastapi import APIRouter, HTTPException, Request

from rknmon.agent.config import AgentSettings
from rknmon.custom_metrics import (
    XrayProfileLabel,
    clear_xray_profile_metrics,
    prune_xray_profile_metrics,
    record_dpi_probe,
    record_probe_latency,
    record_probe_result,
    record_subscription_health,
    record_xray_probe,
)
from rknmon.db import execute, fetch, fetchrow
from rknmon.dpi_vantage import adjust_hypothesis_with_vantage
from rknmon.models.schemas import (
    AgentHeartbeatIn,
    AgentProbeBatchIn,
    AgentRegisterIn,
    DpiProbeBatchIn,
    SubscriptionHealthBatchIn,
    XrayProbeBatchIn,
)
from rknmon.probes.evaluator import evaluate_targets

router = APIRouter(prefix="/agent", tags=["agent"])


def _poll_interval_seconds() -> int:
    try:
        return AgentSettings().probe_interval_seconds
    except Exception:
        return int(os.getenv("PROBE_INTERVAL_SECONDS", "300"))


def _dpi_vantage_match_window_seconds() -> int:
    return int(os.getenv("DPI_VANTAGE_MATCH_WINDOW_SECONDS", "900"))


async def _get_probe_node(request: Request) -> dict:
    api_key = request.headers.get("X-Node-API-Key")
    if not api_key:
        raise HTTPException(status_code=403, detail="Forbidden: missing node API key")
    row = await fetchrow(
        "SELECT id, name, role, is_active FROM probe_nodes WHERE api_key = $1",
        api_key,
    )
    if not row or not row.get("is_active", False):
        raise HTTPException(status_code=403, detail="Forbidden: invalid node API key")
    return dict(row)


async def _corroborate_dpi_hypothesis(node: dict, probe) -> dict:
    details = dict(probe.details or {})
    if (
        node.get("role") != "subject"
        or probe.checker != "mechanism-inference"
        or details.get("hypothesis") != "dns_interference"
    ):
        return details

    rows = await fetch(
        """
        SELECT DISTINCT ON (n.id)
            n.name AS agent,
            n.role,
            d.ok,
            d.error_type,
            d.checked_at
        FROM dpi_probe_results d
        JOIN probe_nodes n ON n.id = d.probe_node_id
        WHERE d.checker = 'dns'
          AND d.target = $1
          AND n.role IN ('control', 'external')
          AND d.checked_at >= now() - ($2::double precision * interval '1 second')
        ORDER BY n.id, d.checked_at DESC
        """,
        probe.target,
        float(_dpi_vantage_match_window_seconds()),
    )
    return adjust_hypothesis_with_vantage(details, [dict(row) for row in rows])


def _is_self_registration_via_invite() -> bool:
    return os.getenv("RKNMON_ALLOW_DIRECT_REGISTRATION", "false").lower() in {
        "1", "true", "yes"
    }


@router.post("/register")
async def agent_register(request: Request, payload: AgentRegisterIn):
    api_key = request.headers.get("X-Node-API-Key")
    if not api_key:
        raise HTTPException(status_code=403, detail="Forbidden: missing node API key")

    existing = await fetchrow(
        "SELECT id, name, is_active FROM probe_nodes WHERE api_key = $1", api_key
    )
    if existing:
        await execute(
            """
            UPDATE probe_nodes
            SET last_seen_at = now(),
                last_ip = COALESCE($2, last_ip),
                agent_version = COALESCE($3, agent_version),
                location = COALESCE($4, location),
                provider = COALESCE($5, provider),
                role = COALESCE($6, role),
                is_active = true
            WHERE id = $1
            """,
            existing["id"],
            payload.public_ip,
            payload.agent_version,
            payload.location,
            payload.provider,
            payload.role,
        )
        return {
            "probe_node_id": existing["id"],
            "name": existing["name"],
            "is_active": existing["is_active"],
            "role": payload.role,
            "poll_interval_seconds": _poll_interval_seconds(),
            "registration": "existing",
        }

    if payload.bootstrap_token:
        from rknmon.api.agent_invites import bootstrap_agent
        try:
            bootstrap_out, _ = await bootstrap_agent(
                token=payload.bootstrap_token,
                name=payload.name,
                location=payload.location,
                provider=payload.provider,
                public_ip=payload.public_ip,
                agent_version=payload.agent_version,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {
            "probe_node_id": None,
            "name": bootstrap_out.agent_name,
            "is_active": True,
            "poll_interval_seconds": _poll_interval_seconds(),
            "registration": "bootstrap_pending",
            "bootstrap": bootstrap_out.model_dump(),
        }

    if not _is_self_registration_via_invite():
        raise HTTPException(
            status_code=403,
            detail=(
                "Forbidden: this central requires invite-based registration. "
                "POST /agent/bootstrap with a one-time token to enroll."
            ),
        )

    await execute(
        """
        INSERT INTO probe_nodes (
            name, api_key, location, provider, role,
            last_seen_at, last_ip, agent_version, is_active
        )
        VALUES ($1, $2, $3, $4, $5, now(), $6, $7, true)
        ON CONFLICT (api_key) DO UPDATE SET
            name = EXCLUDED.name,
            location = EXCLUDED.location,
            provider = EXCLUDED.provider,
            role = EXCLUDED.role,
            last_seen_at = now(),
            last_ip = EXCLUDED.last_ip,
            agent_version = EXCLUDED.agent_version,
            is_active = true
        """,
        payload.name,
        api_key,
        payload.location,
        payload.provider,
        payload.role,
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
        "role": payload.role,
        "poll_interval_seconds": _poll_interval_seconds(),
        "registration": "legacy",
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
        node["id"], payload.public_ip, payload.agent_version,
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
            INSERT INTO probes (
                target_id, probe_node_id, probe_type, status_code,
                response_time_ms, body_hash, error, resolver, result
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            probe.target_id, node["id"], probe.probe_type, probe.status_code,
            probe.response_time_ms, probe.body_hash, probe.error, probe.resolver,
            json.dumps(probe.result or {}),
        )
        domain = target_domains.get(probe.target_id, str(probe.target_id))
        if probe.response_time_ms is not None:
            record_probe_latency(str(probe.target_id), domain, probe.probe_type, probe.response_time_ms)
        record_probe_result(
            agent=node["name"],
            target_id=str(probe.target_id),
            domain=domain,
            probe_type=probe.probe_type,
            status_code=probe.status_code,
            error=probe.error,
            result=probe.result,
            response_time_ms=probe.response_time_ms,
        )

    await evaluate_targets(sorted(touched_target_ids))
    return {"accepted": len(payload.results), "probe_node_id": node["id"]}


@router.post("/xray-results")
async def ingest_xray_probe_batch(request: Request, payload: XrayProbeBatchIn):
    node = await _get_probe_node(request)
    current_by_subscription: dict[str, set[XrayProfileLabel]] = {}
    for probe in payload.results:
        await execute(
            """
            INSERT INTO xray_probe_results (
                probe_node_id, profile_id, profile_name, subscription_name,
                protocol, transport, security, sni, fingerprint, server_host,
                server_port, socks_port, test_url, ok, latency_ms, http_status,
                bytes_downloaded, error_type, error, details
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                $11, $12, $13, $14, $15, $16, $17, $18, $19, $20
            )
            """,
            node["id"], probe.profile_id, probe.profile_name, probe.subscription_name,
            probe.protocol, probe.transport, probe.security, probe.sni, probe.fingerprint,
            probe.server_host, probe.server_port, probe.socks_port, probe.test_url,
            probe.ok, probe.latency_ms, probe.http_status, probe.bytes_downloaded,
            probe.error_type, probe.error, json.dumps(probe.details or {}),
        )
        subscription = probe.subscription_name or "default"
        label_tuple: XrayProfileLabel = (
            node["name"], subscription, probe.profile_id, probe.protocol,
            probe.transport or "unknown", probe.security or "none", probe.server_host,
        )
        current_by_subscription.setdefault(subscription, set()).add(label_tuple)
        record_xray_probe(
            agent=node["name"],
            subscription=probe.subscription_name,
            profile=probe.profile_id,
            protocol=probe.protocol,
            transport=probe.transport,
            security=probe.security,
            server=probe.server_host,
            ok=probe.ok,
            latency_ms=probe.latency_ms,
            error_type=probe.error_type,
            details=probe.details,
        )
    for subscription, current in current_by_subscription.items():
        prune_xray_profile_metrics(node["name"], subscription, current)
    return {"accepted": len(payload.results), "probe_node_id": node["id"]}


@router.post("/dpi-results")
async def ingest_dpi_probe_batch(request: Request, payload: DpiProbeBatchIn):
    node = await _get_probe_node(request)
    for probe in payload.results:
        details = await _corroborate_dpi_hypothesis(node, probe)
        await execute(
            """
            INSERT INTO dpi_probe_results (
                probe_node_id, checker, target, method, ok, latency_ms,
                http_status, error_type, error, details
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            node["id"], probe.checker, probe.target, probe.method, probe.ok,
            probe.latency_ms, probe.http_status, probe.error_type, probe.error,
            json.dumps(details),
        )
        record_dpi_probe(
            agent=node["name"],
            checker=probe.checker,
            target=probe.target,
            method=probe.method,
            ok=probe.ok,
            latency_ms=probe.latency_ms,
            error_type=probe.error_type,
            details=details,
        )
    return {"accepted": len(payload.results), "probe_node_id": node["id"]}


@router.post("/subscription-health")
async def ingest_subscription_health(request: Request, payload: SubscriptionHealthBatchIn):
    node = await _get_probe_node(request)
    for item in payload.items:
        await execute(
            """
            INSERT INTO xray_subscription_health (
                probe_node_id, subscription_name, subscription_url, ok,
                http_status, error_type, error, profiles_count
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            node["id"], item.subscription_name, item.subscription_url, item.ok,
            item.http_status, item.error_type, item.error, item.profiles_count,
        )
        record_subscription_health(
            agent=node["name"],
            subscription=item.subscription_name,
            ok=item.ok,
            http_status=item.http_status,
            error_type=item.error_type,
        )
        if not item.ok:
            clear_xray_profile_metrics(node["name"], item.subscription_name)
    return {"accepted": len(payload.items), "probe_node_id": node["id"]}
