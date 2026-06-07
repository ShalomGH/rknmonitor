from __future__ import annotations
import logging
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

def record_event(event_type: str) -> None:
    EVENTS_COUNTER.labels(event_type=event_type).inc()

def record_probe_latency(target_id: str, domain: str, probe_type: str, ms: float) -> None:
    PROBE_LATENCY_GAUGE.labels(
        target_id=str(target_id), domain=domain, probe_type=probe_type
    ).set(ms)

def set_active_targets(count: int) -> None:
    ACTIVE_TARGETS_GAUGE.set(count)
