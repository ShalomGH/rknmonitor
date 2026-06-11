# DPI Dashboard Clarity Redesign — Design Spec

Date: 2026-06-11
Project: `rkn-blocks-monitoring`
Dashboard: `grafana/dashboards/dpi.json` (`uid: rknmon-dpi`)

## 1. Goal

Make the DPI Grafana dashboard understandable at a glance while preserving enough detail for real diagnostics.

The dashboard should answer three operator questions in order:

1. Is there a DPI/connectivity problem right now?
2. What exactly is affected: target, agent/provider, method, or error type?
3. How has it changed over time?

## 2. Current state

Current `rknmon-dpi` has 5 panels:

- `DPI OK checks` stat
- `DPI failed/suspected` stat
- `DPI latency` timeseries
- `Current DPI check status` table from Prometheus
- `Latest DPI rows from DB` table from Postgres

This exposes raw data, but the hierarchy is weak: the user sees metrics before getting a clear operational verdict.

## 3. Approved direction

Use a mixed layout:

- **A: operational top** — simple answer: healthy / degraded / failing, affected targets, affected agents, latest failure.
- **B: diagnostic matrix** — target × agent/method view to distinguish local ISP issues from global target problems or method-specific DPI behavior.
- **History block** — latency and status over time for the selected scope.

Do not build the full “runbook verdict / evidence / next step” panel yet. It is valuable later, but should wait until there is backend classification or robust SQL/PromQL logic behind it.

## 4. Dashboard structure

### 4.1 Variables / filters

Keep dashboard-wide filters simple and visible:

- `agent` — existing agent filter, multi-select/all.
- `method` — DPI check method if present in labels/DB.
- `target` — target/domain selector for drill-down history.
- Time range — Grafana native time picker.

Timezone remains `Asia/Omsk`.

### 4.2 Top row: operational KPI panels

Four stat panels at the top:

1. **Overall DPI status**
   - Purpose: one-word health indicator.
   - Values: `OK`, `Degraded`, `Failing`, or `No data`.
   - Color:
     - green: no current failures
     - yellow: partial/suspected/slow failures
     - red: active hard failures
     - gray: no data

2. **Affected targets**
   - Count of current targets with failed/suspected DPI checks.
   - Prefer current/latest status over raw count of failed samples.

3. **Affected agents**
   - Count/list signal for probe nodes currently seeing failures.
   - This helps distinguish one-provider issues from broader events.

4. **Latest failure age**
   - Relative time since latest failed/suspected row.
   - Shows whether the incident is fresh or stale.

### 4.3 Second block: “What is happening” table

Replace or refine raw tables into one operator-friendly table.

Columns:

- `agent`
- `target`
- `method`
- `status` — `ok`, `slow`, `fail`, `suspected`, `inconclusive`
- `latency_ms`
- `error_type`
- `http_status`
- `checked_at`

Sorting:

1. failing/suspected rows first
2. then slow rows
3. then newest `checked_at`

Display rules:

- Use status text plus color. Do not rely on color alone.
- Hide noisy raw labels unless they help diagnose.
- If possible, add data links or dashboard links from a row to filtered history for that target/agent.

### 4.4 Third block: diagnostic matrix

Add a matrix-style panel to show cross-comparison:

- Rows: targets.
- Columns: agent/method combinations, or agent first if method cardinality is too high.
- Cell value: latest status text/value.
- Cell color: green/yellow/red/gray.

Intent:

- If only one agent is red and others are green → likely local ISP/provider path.
- If all agents are red for one target → target outage or global block.
- If only one method is red → likely protocol/SNI/DPI-method-specific behavior.

Grafana implementation options, in order:

1. Postgres table query with pivot-like output if practical.
2. Grafana table panel with transformations.
3. Fallback: normal table grouped by target/agent/method if pivot becomes too brittle.

### 4.5 Lower block: history

Keep a history section below the operational and diagnostic blocks:

1. **DPI latency over time**
   - Filtered by `agent`, `method`, and optionally `target`.
   - Useful for detecting throttling or degradation before hard failure.

2. **Status history**
   - Prefer `state-timeline` or `status-history` if it renders cleanly.
   - Fallback to timeseries/table if Grafana timeline behaves poorly.
   - Use explicit status mappings, not just raw 0/1.

## 5. Data source strategy

Use both existing data sources intentionally:

- Prometheus:
  - fast aggregate stats
  - current metric status
  - latency time series
- Postgres:
  - latest rows table
  - target/agent/method matrix
  - richer columns like `error_type`, `http_status`, `checked_at`

Avoid changing metric names or backend schema in this iteration unless a panel cannot be built reliably from existing data.

## 6. Error handling and no-data behavior

Every major panel must handle empty data explicitly:

- Top status should show `No data`, not green `0`, if no DPI samples exist.
- Tables should show useful empty-state titles/descriptions where Grafana supports them.
- Matrix should include `inconclusive`/gray for missing samples rather than pretending OK.

## 7. Visual style

Keep Grafana-native visuals, but improve hierarchy:

- Top row: large stat cards, short titles.
- Middle: table/matrix with text statuses and color mapping.
- Bottom: historical charts.
- Avoid cluttered titles like raw metric names.
- Use Russian/operator-friendly wording where it improves comprehension, but keep field names technical where they map directly to DB/labels (`agent`, `target`, `method`, `error_type`).

## 8. Testing / verification

After implementation:

1. Validate dashboard JSON parses.
2. Run existing test suite, especially Grafana dashboard tests.
3. Verify datasource UIDs remain valid:
   - Prometheus datasource UID as provisioned.
   - Postgres datasource UID `grafana-postgres`.
4. Recreate/reload Grafana provisioning.
5. Verify via Grafana API that dashboard `rknmon-dpi` loads and panels are present.
6. Visually check the rendered dashboard in browser.

## 9. Out of scope for this iteration

- Backend incident classification engine.
- Alerting rules.
- New DB schema tables.
- Changing agent probe logic.
- Making a separate custom HTML dashboard.

## 10. Open implementation notes

- If Grafana transformations make the matrix fragile, prefer a clear SQL-backed table over a clever but brittle pivot.
- Preserve panel IDs where practical, but readability is more important than keeping old IDs.
- Preserve `uid: rknmon-dpi`, title, variables, and timezone.
- Do not commit secrets or `.env` files.
