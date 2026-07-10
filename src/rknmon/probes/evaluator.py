from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, List

from rknmon.alerts.webhook import batch_send
from rknmon.db import fetch
from rknmon.probes.classifier import classify
from rknmon.probes.state_engine import (
    refresh_event_metric_labels,
    refresh_target_state_metrics,
    update_target_state,
)

logger = logging.getLogger(__name__)

_COMPARISON_ROLES = {"control", "external"}


def _decode_jsonb(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def _match_window_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("VANTAGE_MATCH_WINDOW_SECONDS", "900")))
    except ValueError:
        return 900.0


def _http_reachable(result: dict[str, Any] | None) -> bool:
    if not result:
        return False
    reachable = result.get("reachable")
    if isinstance(reachable, bool):
        return reachable
    if result.get("error"):
        return False
    status = result.get("status_code")
    return isinstance(status, int) and status < 500


def _timestamps_match(
    subject_at: datetime | None,
    comparison_at: datetime | None,
    *,
    now: datetime,
    window_seconds: float,
) -> bool:
    # Older tests and imported legacy rows may not provide timestamps. Preserve
    # compatibility only when both are absent; production probe rows have checked_at.
    if subject_at is None and comparison_at is None:
        return True
    if subject_at is None or comparison_at is None:
        return False

    subject_ts = subject_at if subject_at.tzinfo else subject_at.replace(tzinfo=timezone.utc)
    comparison_ts = (
        comparison_at if comparison_at.tzinfo else comparison_at.replace(tzinfo=timezone.utc)
    )
    if (now - subject_ts).total_seconds() > window_seconds:
        return False
    if (now - comparison_ts).total_seconds() > window_seconds:
        return False
    return abs((subject_ts - comparison_ts).total_seconds()) <= window_seconds


async def evaluate_targets(target_ids: List[int] | None = None) -> List[dict]:
    if target_ids is None:
        t_rows = await fetch("SELECT id, domain FROM targets WHERE is_active = true")
    else:
        t_rows = await fetch(
            "SELECT id, domain FROM targets WHERE is_active = true AND id = any($1)",
            target_ids,
        )

    if not t_rows:
        return []

    ids = [int(r["id"]) for r in t_rows]

    node_rows = await fetch(
        """
        SELECT DISTINCT p.probe_node_id, pn.role, pn.name
        FROM probes p
        JOIN probe_nodes pn ON pn.id = p.probe_node_id
        WHERE p.target_id = any($1) AND p.probe_node_id IS NOT NULL
        ORDER BY p.probe_node_id
        """,
        ids,
    )
    probe_node_ids = [int(r["probe_node_id"]) for r in node_rows]
    if not probe_node_ids:
        return []

    node_roles = {
        int(r["probe_node_id"]): str(r.get("role") or "subject")
        for r in node_rows
    }
    node_names = {
        int(r["probe_node_id"]): str(r.get("name") or r["probe_node_id"])
        for r in node_rows
    }

    http_rows = await fetch(
        """
        SELECT DISTINCT ON (target_id, probe_node_id)
            target_id, probe_node_id, result, checked_at
        FROM probes
        WHERE target_id = any($1) AND probe_node_id = any($2) AND probe_type = 'http'
        ORDER BY target_id, probe_node_id, checked_at DESC
        """,
        ids,
        probe_node_ids,
    )
    dns_rows = await fetch(
        """
        SELECT DISTINCT ON (target_id, probe_node_id)
            target_id, probe_node_id, result, checked_at
        FROM probes
        WHERE target_id = any($1) AND probe_node_id = any($2) AND probe_type = 'dns'
        ORDER BY target_id, probe_node_id, checked_at DESC
        """,
        ids,
        probe_node_ids,
    )

    http_map = {
        (int(r["target_id"]), int(r["probe_node_id"])): (
            _decode_jsonb(r["result"]),
            r.get("checked_at"),
        )
        for r in http_rows
    }
    dns_map = {
        (int(r["target_id"]), int(r["probe_node_id"])): _decode_jsonb(r["result"])
        for r in dns_rows
    }

    now = datetime.now(timezone.utc)
    window_seconds = _match_window_seconds()
    events: List[dict] = []

    for tid in ids:
        for probe_node_id in probe_node_ids:
            http_result, checked_at = http_map.get((tid, probe_node_id), (None, None))
            role = node_roles.get(probe_node_id, "subject")
            external_reachable: bool | None = None
            comparison_details: dict[str, Any] | None = None

            if role == "subject" and http_result is not None:
                matched = []
                for comparison_node_id in probe_node_ids:
                    comparison_role = node_roles.get(comparison_node_id, "subject")
                    if comparison_role not in _COMPARISON_ROLES:
                        continue
                    comparison_result, comparison_at = http_map.get(
                        (tid, comparison_node_id), (None, None)
                    )
                    if comparison_result is None or not _timestamps_match(
                        checked_at,
                        comparison_at,
                        now=now,
                        window_seconds=window_seconds,
                    ):
                        continue
                    matched.append(
                        {
                            "probe_node_id": comparison_node_id,
                            "agent": node_names.get(comparison_node_id, str(comparison_node_id)),
                            "role": comparison_role,
                            "reachable": _http_reachable(comparison_result),
                        }
                    )

                if matched:
                    external_reachable = any(item["reachable"] for item in matched)
                    comparison_details = {
                        "matched": matched,
                        "match_window_seconds": window_seconds,
                        "any_comparison_reachable": external_reachable,
                    }

            state, details = classify(
                http_result,
                dns_map.get((tid, probe_node_id)),
                external_reachable=external_reachable,
            )
            if comparison_details is not None:
                details = {**details, "vantage_comparison": comparison_details}

            event = await update_target_state(tid, probe_node_id, state, details)
            if event:
                events.append(event)

    if events:
        await batch_send(events)

    await refresh_target_state_metrics()
    await refresh_event_metric_labels()
    logger.info(
        "Evaluated %s targets across %s nodes, %s state changes",
        len(ids),
        len(probe_node_ids),
        len(events),
    )
    return events
