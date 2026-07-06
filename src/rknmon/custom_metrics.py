from __future__ import annotations
import logging
from collections import defaultdict
from prometheus_client import Gauge, Counter, Info

logger = logging.getLogger(__name__)

# Target state counts (updated by state_engine.py)
TARGET_STATE_GAUGE = Gauge(
    "rknmon_targets_by_state",
    "Number of targets per state",
    ["state"],
)

# Event counters (updated by state_engine.py)
EVENTS_COUNTER = Counter(
    "rknmon_events_total",
    "Total number of events by type",
    ["event_type"],
)

# Probe latency histogram via Prometheus (maps to http_request_duration, but per-target-type)
PROBE_LATENCY_GAUGE = Gauge(
    "rknmon_probe_latest_response_ms",
    "Latest probe response time per target",
    ["target_id", "domain", "probe_type"],
)

# Active probes gauge
ACTIVE_TARGETS_GAUGE = Gauge(
    "rknmon_active_targets",
    "Number of active (is_active=true) targets",
)

# Build info
BUILD_INFO = Info("rknmon_build", "Build metadata")

def set_build_info(version: str, build_date: str = "") -> None:
    BUILD_INFO.info({"version": version, "build_date": build_date})

def update_target_state_metrics(state_counts: dict[str, int]) -> None:
    for state, count in state_counts.items():
        TARGET_STATE_GAUGE.labels(state=state).set(count)
    for state in ("clear", "suspected", "blocked"):
        if state not in state_counts:
            TARGET_STATE_GAUGE.labels(state=state).set(0)

def ensure_event_metric(event_type: str) -> None:
    EVENTS_COUNTER.labels(event_type=event_type).inc(0)


def record_event(event_type: str) -> None:
    ensure_event_metric(event_type)
    EVENTS_COUNTER.labels(event_type=event_type).inc()

def record_probe_latency(target_id: str, domain: str, probe_type: str, ms: float) -> None:
    PROBE_LATENCY_GAUGE.labels(
        target_id=str(target_id), domain=domain, probe_type=probe_type
    ).set(ms)

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

XrayProfileLabel = tuple[str, str, str, str, str, str, str]
_XRAY_PROFILE_LABELS_BY_AGENT_SUB: dict[tuple[str, str], set[XrayProfileLabel]] = defaultdict(set)

XRAY_SUBSCRIPTION_UP_GAUGE = Gauge(
    "rknmon_xray_subscription_up",
    "Latest Xray subscription fetch outcome: 1 ok, 0 failed",
    ["agent", "subscription"],
)

XRAY_SUBSCRIPTION_ERROR_COUNTER = Counter(
    "rknmon_xray_subscription_errors_total",
    "Xray subscription fetch errors by type (per agent, per subscription)",
    ["agent", "subscription", "error_type"],
)

DPI_CHECK_STATUS_GAUGE = Gauge(
    "rknmon_dpi_check_status",
    "Latest DPI checker status: 1 ok, 0 failed/suspected",
    ["agent", "checker", "target", "method"],
)

DPI_CHECK_LATENCY_GAUGE = Gauge(
    "rknmon_dpi_check_latency_ms",
    "Latest DPI checker latency in milliseconds",
    ["agent", "checker", "target", "method"],
)

DPI_CHECK_ERROR_COUNTER = Counter(
    "rknmon_dpi_check_errors_total",
    "DPI checker errors by type",
    ["agent", "checker", "target", "method", "error_type"],
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
    label_tuple: XrayProfileLabel = (
        labels["agent"],
        labels["subscription"],
        labels["profile"],
        labels["protocol"],
        labels["transport"],
        labels["security"],
        labels["server"],
    )
    _XRAY_PROFILE_LABELS_BY_AGENT_SUB[(labels["agent"], labels["subscription"])].add(label_tuple)
    XRAY_PROFILE_STATUS_GAUGE.labels(**labels).set(1 if ok else 0)
    if latency_ms is not None:
        XRAY_PROFILE_LATENCY_GAUGE.labels(**labels).set(latency_ms)
    if not ok:
        XRAY_PROFILE_ERROR_COUNTER.labels(**labels, error_type=error_type or "unknown").inc()


def prune_xray_profile_metrics(agent: str, subscription: str | None, current: set[XrayProfileLabel]) -> None:
    """Remove profile gauges that disappeared from the latest agent batch.

    prometheus_client keeps every Gauge label ever touched for the lifetime of
    the process. Without explicit removal, deleted/dead subscription profiles
    continue to be exported as if they were still alive.
    """
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
    subscription_label = subscription or "default"
    prune_xray_profile_metrics(agent, subscription_label, set())


def record_subscription_health(
    *,
    agent: str,
    subscription: str,
    ok: bool,
    http_status: int | None,
    error_type: str | None,
) -> None:
    labels = {"agent": agent, "subscription": subscription}
    XRAY_SUBSCRIPTION_UP_GAUGE.labels(**labels).set(1 if ok else 0)
    if not ok:
        XRAY_SUBSCRIPTION_ERROR_COUNTER.labels(
            **labels, error_type=error_type or "unknown"
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
) -> None:
    labels = {"agent": agent, "checker": checker, "target": target, "method": method}
    DPI_CHECK_STATUS_GAUGE.labels(**labels).set(1 if ok else 0)
    if latency_ms is not None:
        DPI_CHECK_LATENCY_GAUGE.labels(**labels).set(latency_ms)
    if not ok:
        DPI_CHECK_ERROR_COUNTER.labels(**labels, error_type=error_type or "unknown").inc()


def set_active_targets(count: int) -> None:
    ACTIVE_TARGETS_GAUGE.set(count)
