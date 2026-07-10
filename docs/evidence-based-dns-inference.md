# Evidence-based DNS mechanism inference

`mechanism-inference` is a derived hypothesis row, not a network check. Derived rows are emitted with `ok=true`, so they no longer inflate failed DPI-check counters or appear as failed checks in Grafana.

## DNS evidence pipeline

For every configured DPI target the agent now compares:

1. the system resolver used by the monitored network;
2. Cloudflare DoH;
3. Google DoH;
4. Cloudflare DNS-over-TLS;
5. TCP reachability of selected system and reference A records when answers diverge.

The reference methods are independent observations. Failure of one public resolver does not by itself make the DNS check fail.

### CDN and GeoDNS divergence

Exact A-record equality is no longer required. Public resolvers often return different CDN edges because resolver location and ECS behaviour differ.

When system and reference answers do not overlap but the system-selected address is reachable on the target port, the result is recorded as successful with diagnosis:

`dns_divergence_but_system_ip_reachable`

This prevents ordinary CDN/GeoDNS variation from becoming `dns_interference`.

### Confirmed DNS evidence

The inference layer emits `dns_interference` only for stronger evidence classes:

- `dns_block_ip` — system DNS returned a loopback/private/link-local/reserved-like address; base score `0.92`;
- `dns_mismatch_confirmed` — system answers do not overlap references, system IPs are not TCP-reachable, at least two reference methods returned answers and a reference IP is TCP-reachable; base score `0.88`;
- `dns_resolution_failure_confirmed` — system resolution failed or returned no A records, at least two reference methods returned answers and a reference IP is TCP-reachable; base score `0.68` because a local resolver outage can look identical.

Generic resolver exceptions and timeouts are kept as failures but are **not** automatically promoted to a blocking-mechanism hypothesis.

## Control / external vantage corroboration

When a `subject` agent submits a `dns_interference` hypothesis, central looks for the freshest DNS result for the same target from each `control` or `external` probe node within:

`DPI_VANTAGE_MATCH_WINDOW_SECONDS` (default `900` seconds)

Adjustment rules:

- a fresh successful comparison vantage strengthens the subject-only hypothesis by `+0.07` (capped at `1.0`);
- if fresh comparison vantages show the same DNS failure, confidence is capped at `0.35` because the evidence is no longer subject-network-specific;
- without fresh comparison data, the local score is preserved and marked `local_evidence_only`.

The adjusted confidence and summarized comparison-vantage evidence are persisted in `dpi_probe_results.details` and exported through `rknmon_blocking_hypothesis_score`.

## Interpretation

Scores are evidence weights, not probabilities and not definitive attribution to RKN or an ISP. A strong score means the observed pattern is more consistent with the named mechanism than a single generic availability failure.
