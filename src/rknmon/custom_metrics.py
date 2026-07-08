from __future__ import annotations

from collections import defaultdict
from typing import Any

from prometheus_client import Counter, Gauge, Histogram, Info

TARGET_STATE_GAUGE = Gauge(
    "rknmon_targets_by_state",
    "Number of unique targets per global state",
    ["state"],
)
TARGET_NODE_STATE_GAUGE = Gauge(
    "rknmon_target_node_states",
    "Number of target plus probe-node state rows",
    ["state"],
)
EVENTS_COUNTER = Counter(
    "rknmon_events_total", "Total number of events by type", ["event_type"]
)
PROBE_LATENCY_GAUGE = Gauge(
    "rknmon_probe_latest_response_ms",
    "Latest probe response time per target",
    ["target_id", "domain", "probe_type"],
)
PROBE_STATUS_GAUGE = Gauge(
    "rknmon_probe_status",
    "Latest ordinary probe status: 1 ok, 0 failed/suspected",
    ["agent", "target_id", "domain", "probe_type"],
)
PROBE_RESULTS_COUNTER = Counter(
    "rknmon_probe_results_total",
    "Ordinary probe results by normalized outcome",
    ["agent", "probe_type", "outcome"],
)
PROBE_DURATION_HISTOGRAM = Histogram(
    "rknmon_probe_duration_seconds",
    "Ordinary probe duration distribution",
    ["agent", "probe_type", "outcome"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30),
)
ACTIVE_TARGETS_GAUGE = Gauge("rknmon_active_targets", "Number of active targets")
BUILD_INFO = Info("rknmon_build", "Build metadata")


def set_build_info(version: str, build_date: str = "") -> None:
    BUILD_INFO.info({"version": version, "build_date": build_date})


def update_target_state_metrics(
    global_state_counts: dict[str, int],
    node_state_counts: dict[str, int] | None = None,
) -> None:
    for state in ("clear", "suspected", "blocked"):
        TARGET_STATE_GAUGE.labels(state=state).set(global_state_counts.get(state, 0))
        if node_state_counts is not None:
            TARGET_NODE_STATE_GAUGE.labels(state=state).set(node_state_counts.get(state, 0))


def ensure_event_metric(event_type: str) -> None:
    EVENTS_COUNTER.labels(event_type=event_type).inc(0)


def record_event(event_type: str) -> None:
    ensure_event_metric(event_type)
    EVENTS_COUNTER.labels(event_type=event_type).inc()


def record_probe_latency(target_id: str, domain: str, probe_type: str, ms: float) -> None:
    PROBE_LATENCY_GAUGE.labels(
        target_id=str(target_id), domain=domain, probe_type=probe_type
    ).set(ms)


def classify_probe_outcome(
    *,
    probe_type: str,
    status_code: int | None,
    error: str | None,
    result: dict[str, Any] | None,
) -> str:
    result = result or {}
    error_lower = (error or "").lower()
    if probe_type == "dns":
        if result.get("nxdomain"):
            return "dns_nxdomain"
        if result.get("tampered"):
            return "dns_mismatch"
        resolver_errors = [
            str(item.get("error") or "").lower()
            for item in result.get("results", [])
            if isinstance(item, dict) and item.get("error")
        ]
        if any("timeout" in item for item in resolver_errors):
            return "dns_timeout"
        return "dns_error" if error else "ok"
    if "timeout" in error_lower:
        return "tcp_timeout"
    if "reset" in error_lower or "broken pipe" in error_lower:
        return "tcp_reset"
    if "ssl" in error_lower or "tls" in error_lower or "certificate" in error_lower:
        return "tls_error"
    if status_code == 451:
        return "http_451"
    if status_code == 403:
        return "http_403"
    if error:
        return "network_error"
    if status_code is not None and status_code >= 500:
        return "http_5xx"
    return "ok"


def record_probe_result(
    *,
    agent: str,
    target_id: str,
    domain: str,
    probe_type: str,
    status_code: int | None,
    error: str | None,
    result: dict[str, Any] | None,
    response_time_ms: float | None,
) -> str:
    outcome = classify_probe_outcome(
        probe_type=probe_type, status_code=status_code, error=error, result=result
    )
    PROBE_STATUS_GAUGE.labels(
        agent=agent, target_id=str(target_id), domain=domain, probe_type=probe_type
    ).set(1 if outcome == "ok" else 0)
    PROBE_RESULTS_COUNTER.labels(agent=agent, probe_type=probe_type, outcome=outcome).inc()
    if response_time_ms is not None:
        PROBE_DURATION_HISTOGRAM.labels(
            agent=agent, probe_type=probe_type, outcome=outcome
        ).observe(max(0.0, response_time_ms / 1000.0))
    return outcome


XRAY_PROFILE_STATUS_GAUGE = Gauge(
    "rknmon_xray_profile_status",
    "Latest Xray profile probe status: 1 ok, 0 failed",
    ["agent", "subscription", "profile", "protocol", "transport", "security", "server"],
)
XRAY_PROFILE_LATENCY_GAUGE = Gauge(
    "rknmon_xray_profile_latency_ms",
    "Latest Xray profile probe latency in milliseconds",
    ["agent", "subscription", "profile", "protocol", "transport", "security", "server"],
)
XRAY_PROFILE_ERROR_COUNTER = Counter(
    "rknmon_xray_profile_errors_total",
    "Xray profile probe errors by type",
    ["agent", "subscription", "profile", "protocol", "transport", "security", "server", "error_type"],
)
XRAY_PROBE_DURATION_HISTOGRAM = Histogram(
    "rknmon_xray_probe_duration_seconds",
    "Xray profile probe duration distribution",
    ["agent", "protocol", "transport", "security", "outcome"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30),
)
XRAY_STAGE_DURATION_HISTOGRAM = Histogram(
    "rknmon_xray_stage_duration_seconds",
    "Xray probe stage duration distribution",
    ["agent", "protocol", "transport", "stage", "outcome"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20),
)
XrayProfileLabel = tuple[str, str, str, str, str, str, str]
_XRAY_PROFILE_LABELS_BY_AGENT_SUB: dict[tuple[str, str], set[XrayProfileLabel]] = defaultdict(set)
XRAY_SUBSCRIPTION_UP_GAUGE = Gauge(
    "rknmon_xray_subscription_up", "Latest Xray subscription fetch outcome", ["agent", "subscription"]
)
XRAY_SUBSCRIPTION_ERROR_COUNTER = Counter(
    "rknmon_xray_subscription_errors_total",
    "Xray subscription fetch errors by type",
    ["agent", "subscription", "error_type"],
)

DPI_CHECK_STATUS_GAUGE = Gauge(
    "rknmon_dpi_check_status", "Latest DPI checker status", ["agent", "checker", "target", "method"]
)
DPI_CHECK_LATENCY_GAUGE = Gauge(
    "rknmon_dpi_check_latency_ms", "Latest DPI checker latency", ["agent", "checker", "target", "method"]
)
DPI_CHECK_ERROR_COUNTER = Counter(
    "rknmon_dpi_check_errors_total",
    "DPI checker errors by type",
    ["agent", "checker", "target", "method", "error_type"],
)
DPI_CHECK_DURATION_HISTOGRAM = Histogram(
    "rknmon_dpi_check_duration_seconds",
    "DPI and controlled experiment duration distribution",
    ["agent", "checker", "method", "outcome"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30),
)
PROBE_STAGE_DURATION_HISTOGRAM = Histogram(
    "rknmon_probe_stage_duration_seconds",
    "Controlled experiment stage duration distribution",
    ["agent", "experiment_type", "stage", "outcome"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20),
)
BLOCKING_HYPOTHESIS_GAUGE = Gauge(
    "rknmon_blocking_hypothesis_score",
    "Latest evidence-based blocking mechanism hypothesis score",
    ["agent", "target", "mechanism"],
)
PROBE_ARTIFACT_COUNTER = Counter(
    "rknmon_probe_artifacts_total",
    "Diagnostic artifacts retained by reason and type",
    ["agent", "reason", "artifact_type"],
)


def record_xray_probe(
    *,
    agent: str,
    subscription: str | None,
    profile: str,
    protocol: str,
    transport: str | None,
    security: str | None,
    server: str,
    ok: bool,
    latency_ms: float | None,
    error_type: str | None,
    details: dict[str, Any] | None = None,
) -> None:
    labels = {
        "agent": agent,
        "subscription": subscription or "default",
        "profile": profile,
        "protocol": protocol,
        "transport": transport or "unknown",
        "security": security or "none",
        "server": server,
    }
    label_tuple: XrayProfileLabel = tuple(labels[k] for k in (
        "agent", "subscription", "profile", "protocol", "transport", "security", "server"
    ))  # type: ignore[assignment]
    _XRAY_PROFILE_LABELS_BY_AGENT_SUB[(labels["agent"], labels["subscription"])].add(label_tuple)
    XRAY_PROFILE_STATUS_GAUGE.labels(**labels).set(1 if ok else 0)
    outcome = "ok" if ok else (error_type or "unknown")
    if latency_ms is not None:
        XRAY_PROFILE_LATENCY_GAUGE.labels(**labels).set(latency_ms)
        XRAY_PROBE_DURATION_HISTOGRAM.labels(
            agent=agent,
            protocol=protocol,
            transport=transport or "unknown",
            security=security or "none",
            outcome=outcome,
        ).observe(max(0.0, latency_ms / 1000.0))
    if not ok:
        XRAY_PROFILE_ERROR_COUNTER.labels(**labels, error_type=error_type or "unknown").inc()
    for stage in (details or {}).get("stages", []):
        if isinstance(stage, dict) and stage.get("duration_ms") is not None:
            XRAY_STAGE_DURATION_HISTOGRAM.labels(
                agent=agent,
                protocol=protocol,
                transport=transport or "unknown",
                stage=str(stage.get("stage") or "unknown"),
                outcome=str(stage.get("outcome") or "unknown"),
            ).observe(max(0.0, float(stage["duration_ms"]) / 1000.0))


def prune_xray_profile_metrics(agent: str, subscription: str | None, current: set[XrayProfileLabel]) -> None:
    subscription_label = subscription or "default"
    key = (agent, subscription_label)
    stale = _XRAY_PROFILE_LABELS_BY_AGENT_SUB[key] - current
    for label_tuple in stale:
        try:
            XRAY_PROFILE_STATUS_GAUGE.remove(*label_tuple)
            XRAY_PROFILE_LATENCY_GAUGE.remove(*label_tuple)
        except KeyError:
            pass
    _XRAY_PROFILE_LABELS_BY_AGENT_SUB[key] = set(current)


def clear_xray_profile_metrics(agent: str, subscription: str | None) -> None:
    prune_xray_profile_metrics(agent, subscription or "default", set())


def record_subscription_health(
    *, agent: str, subscription: str, ok: bool, http_status: int | None, error_type: str | None
) -> None:
    XRAY_SUBSCRIPTION_UP_GAUGE.labels(agent=agent, subscription=subscription).set(1 if ok else 0)
    if not ok:
        XRAY_SUBSCRIPTION_ERROR_COUNTER.labels(
            agent=agent, subscription=subscription, error_type=error_type or "unknown"
        ).inc()


def record_dpi_probe(
    *,
    agent: str,
    checker: str,
    target: str,
    method: str,
    ok: bool,
    latency_ms: float | None,
    error_type: str | None,
    details: dict[str, Any] | None = None,
) -> None:
    labels = {"agent": agent, "checker": checker, "target": target, "method": method}
    DPI_CHECK_STATUS_GAUGE.labels(**labels).set(1 if ok else 0)
    outcome = "ok" if ok else (error_type or "unknown")
    if latency_ms is not None:
        DPI_CHECK_LATENCY_GAUGE.labels(**labels).set(latency_ms)
        DPI_CHECK_DURATION_HISTOGRAM.labels(
            agent=agent, checker=checker, method=method, outcome=outcome
        ).observe(max(0.0, latency_ms / 1000.0))
    if not ok:
        DPI_CHECK_ERROR_COUNTER.labels(**labels, error_type=error_type or "unknown").inc()

    details = details or {}
    experiment_type = str(details.get("experiment_type") or checker)
    for stage in details.get("stages", []):
        if isinstance(stage, dict) and stage.get("duration_ms") is not None:
            PROBE_STAGE_DURATION_HISTOGRAM.labels(
                agent=agent,
                experiment_type=experiment_type,
                stage=str(stage.get("stage") or "unknown"),
                outcome=str(stage.get("outcome") or "unknown"),
            ).observe(max(0.0, float(stage["duration_ms"]) / 1000.0))
    if details.get("hypothesis") and details.get("confidence") is not None:
        BLOCKING_HYPOTHESIS_GAUGE.labels(
            agent=agent, target=target, mechanism=str(details["hypothesis"])
        ).set(float(details["confidence"]))
    for artifact in details.get("artifacts", []):
        if isinstance(artifact, dict):
            PROBE_ARTIFACT_COUNTER.labels(
                agent=agent,
                reason=str(artifact.get("reason") or "unknown"),
                artifact_type=str(artifact.get("artifact_type") or "unknown"),
            ).inc()


def set_active_targets(count: int) -> None:
    ACTIVE_TARGETS_GAUGE.set(count)
