# Blocking mechanism telemetry

This document describes the opt-in telemetry added for distinguishing a generic
availability failure from a likely blocking mechanism.

## Safety and scope

Controlled A/B experiments must target endpoints you own or are explicitly
authorized to test. The feature is disabled by default.

## Vantage roles

Agents can declare:

- `subject`: network under test;
- `control`: trusted comparison path;
- `external`: outside comparison vantage.

Central scheduler probes are stored as an internal `control` node instead of
`probe_node_id=NULL`, so they participate in multi-vantage evaluation without
creating an API credential.

## Metrics

Ordinary probes:

- `rknmon_probe_status{agent,target_id,domain,probe_type}`
- `rknmon_probe_results_total{agent,probe_type,outcome}`
- `rknmon_probe_duration_seconds{agent,probe_type,outcome}`

State semantics:

- `rknmon_targets_by_state{state}` counts unique targets after worst-state
  aggregation across vantages;
- `rknmon_target_node_states{state}` counts raw target+node state rows.

Stage and experiment metrics:

- `rknmon_probe_stage_duration_seconds{agent,experiment_type,stage,outcome}`
- `rknmon_dpi_check_duration_seconds{agent,checker,method,outcome}`
- `rknmon_blocking_hypothesis_score{agent,target,mechanism}`

Xray:

- existing latest status/latency metrics remain;
- `rknmon_xray_probe_duration_seconds` adds distributions;
- `rknmon_xray_stage_duration_seconds` adds stage timing;
- Xray rows persist `details` JSONB with curl exit code, remote IP and stages.

## Normalized ordinary outcomes

The first taxonomy intentionally stays small:

- `ok`
- `dns_nxdomain`
- `dns_mismatch`
- `dns_timeout`
- `dns_error`
- `tcp_timeout`
- `tcp_reset`
- `tls_error`
- `http_403`
- `http_451`
- `http_5xx`
- `network_error`

Raw evidence remains in PostgreSQL.

## Controlled experiments

Enable with:

```env
DPI_EXPERIMENTS_ENABLED=true
DPI_EXPERIMENT_TARGETS=control=https://control.example.com/
DPI_SNI_VARIANTS=correct,none,allowed.example
DPI_HOST_VARIANTS=correct,allowed.example
DPI_UDP_TARGETS=echo=203.0.113.10:9443
DPI_HTTP3_TARGETS=https://control.example.com/
```

### TLS/SNI A/B

For one resolved destination IP and port, variants change only SNI while keeping
the target path and HTTP Host stable.

Stages:

1. DNS
2. TCP connect
3. TLS handshake
4. HTTP first byte
5. HTTP total

### HTTP Host A/B

Keeps destination IP, port and SNI stable while changing only the HTTP Host
header.

### UDP echo

Requires a controlled endpoint that echoes the exact datagram payload. A
failure is evidence of a UDP path problem, not by itself proof of censorship.

### HTTP/3

Uses `curl --http3-only`. If the installed curl lacks HTTP/3 support, the result
is recorded as an explicit capability/error outcome rather than silently
treated as success.

## Hypothesis inference

The agent emits `mechanism-inference` rows with:

- `hypothesis`
- `confidence`
- `evidence`

Current hypotheses are deliberately conservative:

- `dns_interference`
- `allowlisting`
- `sni_filter`
- `http_host_filter`
- `quic_or_udp_interference`
- `udp_path_interference`
- `rst_or_tcp_interference`

These are hypotheses, not definitive attribution. Confidence rises only when
controlled variants diverge while other variables stay stable.

## Cardinality policy

Prometheus keeps operational dimensions only. Raw IPs, SNI values, response
samples and detailed stage evidence stay in PostgreSQL JSONB.

Per-profile Xray series are retained for backwards compatibility, but new
histograms deliberately aggregate by protocol/transport/security rather than
profile/server.

## Migration notes

`probes.response_time_ms` is migrated to `DOUBLE PRECISION`.

`probe_nodes.api_key` becomes nullable so internal control nodes can exist
without a usable agent credential.

`xray_probe_results.details JSONB` stores stage evidence.
