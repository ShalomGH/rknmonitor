# Reliability metrics and matched-vantage semantics

## Scope

This change set focuses on data trustworthiness before adding more probe types.

## Freshness

Prometheus exports:

- `rknmon_agent_last_seen_timestamp_seconds{agent,role}`
- `rknmon_probe_last_completed_timestamp_seconds{agent,probe_type}`
- `rknmon_probe_last_success_timestamp_seconds{agent,probe_type}`
- `rknmon_blocking_hypothesis_last_evidence_timestamp_seconds{agent,target,mechanism}`

These timestamps let dashboards distinguish a genuinely healthy current value from a stale gauge.

## Agent-aware latency

`rknmon_probe_latest_response_ms` includes `agent`, so different vantage points no longer overwrite the same time series.

## Hypothesis lifecycle

Each submitted DPI batch is treated as one agent cycle. Blocking hypotheses present in the current batch remain exported. Hypotheses absent from the next batch are removed from both score and last-evidence gauges.

## Matched vantage comparison

A `subject` result may use `control` or `external` HTTP evidence only when:

- the target is identical;
- both measurements are recent;
- their timestamps are within `VANTAGE_MATCH_WINDOW_SECONDS` (default 900 seconds).

A fresh reachable comparison path can confirm a failing subject path as blocked. Stale comparison evidence is ignored.

## Global state

Global target state prefers the worst state among `subject` rows. `control` and `external` failures are evidence inputs and do not globally block a target when subject rows exist. Targets without a subject row fall back to all available roles.

## Grafana

`RKN Monitor — Свежесть и достоверность данных` shows:

- stale agents;
- stale completed probes;
- age of last successful probe;
- hypothesis evidence age;
- per-agent latency after adding the `agent` label.
