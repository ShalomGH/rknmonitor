# DPI Dashboard Clarity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework `rknmon-dpi` Grafana dashboard so the top answers “is DPI broken?”, the middle explains “what is affected?”, and the bottom keeps latency/status history for drill-down.

**Architecture:** This is a Grafana JSON-only change plus dashboard-specific tests. Use existing Prometheus metrics for aggregate/current status and existing Postgres `dpi_probe_results` rows for operator-friendly tables. Do not change backend schema, agent logic, metric names, Docker compose, or secrets.

**Tech Stack:** Grafana provisioned dashboard JSON, Prometheus datasource UID `PBFA97CFB590B2093`, Postgres datasource UID `grafana-postgres`, Python `json` tests with `pytest`.

---

## Files and responsibilities

- Modify: `grafana/dashboards/dpi.json`
  - Preserve `uid: rknmon-dpi`, `title: RKN DPI checks`, `timezone: Asia/Omsk`.
  - Replace the 5 raw panels with a clearer layout: KPI row, operator table, diagnostic matrix/table, latency history, status history.
  - Add/keep variables for `agent`, `method`, and `target` where possible.

- Create: `tests/test_grafana_dpi_dashboard.py`
  - Validate the DPI dashboard JSON structure, datasource UIDs, variables, panel titles, and important query fragments.
  - These tests are intentionally structural: they catch accidental datasource/query/panel regressions without needing a live Grafana.

- Optional modify: `docs/superpowers/specs/2026-06-11-dpi-dashboard-clarity-design.md`
  - Only if implementation discovers a Grafana limitation that changes the approved design.

---

## Task 1: Add failing structural tests for the new dashboard shape

**Files:**
- Create: `tests/test_grafana_dpi_dashboard.py`
- Read: `grafana/dashboards/dpi.json`

- [ ] **Step 1: Create the test file**

Create `tests/test_grafana_dpi_dashboard.py` with this content:

```python
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_FILE = ROOT / "grafana/dashboards/dpi.json"
PROM_UID = "PBFA97CFB590B2093"
POSTGRES_UID = "grafana-postgres"


def load_dashboard():
    return json.loads(DASHBOARD_FILE.read_text())


def panel_by_title(dashboard, title):
    matches = [p for p in dashboard["panels"] if p.get("title") == title]
    assert matches, f"Expected panel titled {title!r}"
    return matches[0]


def target_text(panel):
    return "\n".join(
        (target.get("expr") or target.get("rawSql") or "")
        for target in panel.get("targets", [])
    )


def test_dpi_dashboard_identity_and_timezone():
    dashboard = load_dashboard()

    assert dashboard["uid"] == "rknmon-dpi"
    assert dashboard["title"] == "RKN DPI checks"
    assert dashboard["timezone"] == "Asia/Omsk"


def test_dpi_dashboard_has_operator_variables():
    dashboard = load_dashboard()
    variables = {item["name"]: item for item in dashboard["templating"]["list"]}

    assert {"agent", "method", "target"}.issubset(variables)
    assert variables["agent"]["datasource"]["uid"] == PROM_UID
    assert "label_values(rknmon_dpi_check_status, agent)" in str(variables["agent"]["query"])
    assert variables["method"]["datasource"]["uid"] == PROM_UID
    assert "label_values(rknmon_dpi_check_status" in str(variables["method"]["query"])
    assert variables["target"]["datasource"]["uid"] == PROM_UID
    assert "label_values(rknmon_dpi_check_status" in str(variables["target"]["query"])


def test_dpi_dashboard_has_operational_kpi_row():
    dashboard = load_dashboard()

    for title in [
        "Overall DPI status",
        "Affected targets",
        "Affected agents",
        "Latest failure age",
    ]:
        panel = panel_by_title(dashboard, title)
        assert panel["type"] == "stat"
        assert panel["gridPos"]["y"] == 0

    overall = panel_by_title(dashboard, "Overall DPI status")
    assert overall["datasource"]["uid"] == PROM_UID
    assert "rknmon_dpi_check_status" in target_text(overall)


def test_dpi_dashboard_has_operator_table_from_postgres():
    dashboard = load_dashboard()
    panel = panel_by_title(dashboard, "What is happening")

    assert panel["type"] == "table"
    assert panel["datasource"]["uid"] == POSTGRES_UID
    sql = target_text(panel)
    assert "FROM dpi_probe_results" in sql
    assert "JOIN probe_nodes" in sql
    for column in ["agent", "target", "method", "status", "latency_ms", "error_type", "http_status", "checked_at"]:
        assert column in sql
    assert "ORDER BY" in sql


def test_dpi_dashboard_has_diagnostic_matrix_from_postgres():
    dashboard = load_dashboard()
    panel = panel_by_title(dashboard, "Diagnostic matrix")

    assert panel["type"] == "table"
    assert panel["datasource"]["uid"] == POSTGRES_UID
    sql = target_text(panel)
    assert "FROM dpi_probe_results" in sql
    assert "agent_method" in sql
    assert "status" in sql
    assert "row_number()" in sql.lower()


def test_dpi_dashboard_has_history_panels():
    dashboard = load_dashboard()

    latency = panel_by_title(dashboard, "DPI latency over time")
    assert latency["type"] == "timeseries"
    assert latency["datasource"]["uid"] == PROM_UID
    assert "rknmon_dpi_check_latency_ms" in target_text(latency)
    assert 'method=~"$method"' in target_text(latency)
    assert 'target=~"$target"' in target_text(latency)

    history = panel_by_title(dashboard, "DPI status history")
    assert history["type"] in {"state-timeline", "status-history", "timeseries", "table"}
    assert history["datasource"]["uid"] in {PROM_UID, POSTGRES_UID}
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
pytest -q tests/test_grafana_dpi_dashboard.py
```

Expected: FAIL because the current dashboard only has `agent` variable and old panel titles such as `DPI OK checks`.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_grafana_dpi_dashboard.py
git commit -m "test: specify clearer DPI dashboard layout"
```

---

## Task 2: Add dashboard variables for method and target

**Files:**
- Modify: `grafana/dashboards/dpi.json`
- Test: `tests/test_grafana_dpi_dashboard.py`

- [ ] **Step 1: Update templating variables**

In `grafana/dashboards/dpi.json`, keep the existing `agent` variable and add two Prometheus query variables:

```json
{
  "current": {"selected": false, "text": "All", "value": ".*"},
  "datasource": {"type": "prometheus", "uid": "PBFA97CFB590B2093"},
  "definition": "label_values(rknmon_dpi_check_status{agent=~\"$agent\"}, method)",
  "hide": 0,
  "includeAll": true,
  "label": "Method",
  "multi": false,
  "name": "method",
  "options": [],
  "query": {
    "query": "label_values(rknmon_dpi_check_status{agent=~\"$agent\"}, method)",
    "refId": "PrometheusVariableQueryEditor-VariableQuery"
  },
  "refresh": 1,
  "regex": "",
  "skipUrlSync": false,
  "sort": 1,
  "type": "query"
}
```

```json
{
  "current": {"selected": false, "text": "All", "value": ".*"},
  "datasource": {"type": "prometheus", "uid": "PBFA97CFB590B2093"},
  "definition": "label_values(rknmon_dpi_check_status{agent=~\"$agent\", method=~\"$method\"}, target)",
  "hide": 0,
  "includeAll": true,
  "label": "Target",
  "multi": false,
  "name": "target",
  "options": [],
  "query": {
    "query": "label_values(rknmon_dpi_check_status{agent=~\"$agent\", method=~\"$method\"}, target)",
    "refId": "PrometheusVariableQueryEditor-VariableQuery"
  },
  "refresh": 1,
  "regex": "",
  "skipUrlSync": false,
  "sort": 1,
  "type": "query"
}
```

- [ ] **Step 2: Validate JSON parses**

Run:

```bash
python3 -m json.tool grafana/dashboards/dpi.json >/tmp/dpi-dashboard.json
```

Expected: exit code 0.

- [ ] **Step 3: Run variable test**

Run:

```bash
pytest -q tests/test_grafana_dpi_dashboard.py::test_dpi_dashboard_has_operator_variables
```

Expected: PASS.

- [ ] **Step 4: Commit variables**

```bash
git add grafana/dashboards/dpi.json
git commit -m "grafana: add DPI dashboard filters"
```

---

## Task 3: Replace top row with operational KPI panels

**Files:**
- Modify: `grafana/dashboards/dpi.json`
- Test: `tests/test_grafana_dpi_dashboard.py`

- [ ] **Step 1: Define the KPI panel layout**

Set four stat panels at `y=0`, each with `h=5`, `w=6`:

- `Overall DPI status`: `x=0`
- `Affected targets`: `x=6`
- `Affected agents`: `x=12`
- `Latest failure age`: `x=18`

- [ ] **Step 2: Add `Overall DPI status` panel**

Use Prometheus datasource UID `PBFA97CFB590B2093` and this query:

```promql
sum(1 - rknmon_dpi_check_status{agent=~"$agent", method=~"$method", target=~"$target"})
```

Panel behavior:

- stat panel
- thresholds: green at `0`, yellow at `1`, red at `3`
- value mappings:
  - `0` → `OK`
  - `1` and `2` → `Degraded`
  - special `null` → `No data`
- color mode: background

- [ ] **Step 3: Add `Affected targets` panel**

Use this PromQL:

```promql
count(count by (target) (rknmon_dpi_check_status{agent=~"$agent", method=~"$method", target=~"$target"} == 0))
```

Panel behavior:

- stat panel
- unit `short`
- thresholds: green at `0`, yellow at `1`, red at `5`

- [ ] **Step 4: Add `Affected agents` panel**

Use this PromQL:

```promql
count(count by (agent) (rknmon_dpi_check_status{agent=~"$agent", method=~"$method", target=~"$target"} == 0))
```

Panel behavior:

- stat panel
- unit `short`
- thresholds: green at `0`, yellow at `1`, red at `3`

- [ ] **Step 5: Add `Latest failure age` panel**

Use this PromQL:

```promql
time() - max(timestamp(rknmon_dpi_check_status{agent=~"$agent", method=~"$method", target=~"$target"} == 0))
```

Panel behavior:

- stat panel
- unit `s`
- thresholds: green at `0`, yellow at `300`, red at `1800`
- no-data should show `No data`

- [ ] **Step 6: Run KPI test**

Run:

```bash
pytest -q tests/test_grafana_dpi_dashboard.py::test_dpi_dashboard_has_operational_kpi_row
```

Expected: PASS.

- [ ] **Step 7: Commit KPI row**

```bash
git add grafana/dashboards/dpi.json
git commit -m "grafana: add DPI operational KPI row"
```

---

## Task 4: Replace raw tables with operator table and diagnostic matrix

**Files:**
- Modify: `grafana/dashboards/dpi.json`
- Test: `tests/test_grafana_dpi_dashboard.py`

- [ ] **Step 1: Add `What is happening` table**

Create a table panel at `x=0`, `y=5`, `w=24`, `h=9` using Postgres datasource `grafana-postgres`.

Use this SQL:

```sql
WITH latest AS (
  SELECT
    n.name AS agent,
    d.target,
    d.method,
    CASE
      WHEN d.ok THEN 'ok'
      WHEN d.error_type IS NULL OR d.error_type = '' THEN 'fail'
      ELSE d.error_type
    END AS status,
    d.latency_ms,
    d.error_type,
    d.http_status,
    d.checked_at,
    row_number() OVER (
      PARTITION BY n.name, d.target, d.method
      ORDER BY d.checked_at DESC
    ) AS rn
  FROM dpi_probe_results d
  JOIN probe_nodes n ON n.id = d.probe_node_id
  WHERE n.name ~ '${agent:regex}'
    AND d.method ~ '${method:regex}'
    AND d.target ~ '${target:regex}'
    AND $__timeFilter(d.checked_at)
)
SELECT
  agent,
  target,
  method,
  status,
  latency_ms,
  error_type,
  http_status,
  checked_at
FROM latest
WHERE rn = 1
ORDER BY
  CASE
    WHEN status = 'ok' THEN 3
    WHEN status = 'slow' THEN 2
    ELSE 1
  END,
  checked_at DESC
LIMIT 100;
```

- [ ] **Step 2: Configure `What is happening` status colors**

Add field overrides or mappings so:

- `ok` → green
- `slow` → yellow
- `fail`, `timeout`, `tcp_rst`, `sni_drop`, `http_block`, `error` → red
- empty/null → gray

If Grafana JSON field overrides are too verbose, keep the table readable with explicit `status` text and basic threshold coloring. Do not remove the text status.

- [ ] **Step 3: Add `Diagnostic matrix` table**

Create a table panel at `x=0`, `y=14`, `w=24`, `h=10` using Postgres datasource `grafana-postgres`.

Use this SQL:

```sql
WITH latest AS (
  SELECT
    n.name AS agent,
    d.target,
    d.method,
    (n.name || ' / ' || d.method) AS agent_method,
    CASE
      WHEN d.ok THEN 'ok'
      WHEN d.error_type IS NULL OR d.error_type = '' THEN 'fail'
      ELSE d.error_type
    END AS status,
    d.checked_at,
    row_number() OVER (
      PARTITION BY n.name, d.target, d.method
      ORDER BY d.checked_at DESC
    ) AS rn
  FROM dpi_probe_results d
  JOIN probe_nodes n ON n.id = d.probe_node_id
  WHERE n.name ~ '${agent:regex}'
    AND d.method ~ '${method:regex}'
    AND d.target ~ '${target:regex}'
    AND $__timeFilter(d.checked_at)
)
SELECT
  target,
  agent_method,
  status,
  checked_at
FROM latest
WHERE rn = 1
ORDER BY
  target,
  agent_method;
```

This is the reliable fallback shape: not a fragile dynamic SQL pivot, but still shows target × agent/method comparison clearly.

- [ ] **Step 4: Run table/matrix tests**

Run:

```bash
pytest -q \
  tests/test_grafana_dpi_dashboard.py::test_dpi_dashboard_has_operator_table_from_postgres \
  tests/test_grafana_dpi_dashboard.py::test_dpi_dashboard_has_diagnostic_matrix_from_postgres
```

Expected: PASS.

- [ ] **Step 5: Commit tables**

```bash
git add grafana/dashboards/dpi.json
git commit -m "grafana: add DPI operator tables"
```

---

## Task 5: Add history panels for latency and status

**Files:**
- Modify: `grafana/dashboards/dpi.json`
- Test: `tests/test_grafana_dpi_dashboard.py`

- [ ] **Step 1: Add `DPI latency over time` timeseries**

Create a timeseries panel at `x=0`, `y=24`, `w=12`, `h=9` using Prometheus datasource `PBFA97CFB590B2093`.

Use this query:

```promql
rknmon_dpi_check_latency_ms{agent=~"$agent", method=~"$method", target=~"$target"}
```

Legend:

```text
{{agent}} / {{target}} / {{method}}
```

Panel behavior:

- unit `ms`
- legend in table mode at bottom
- multi-tooltip

- [ ] **Step 2: Add `DPI status history` state timeline**

Create a `state-timeline` panel at `x=12`, `y=24`, `w=12`, `h=9` using Prometheus datasource `PBFA97CFB590B2093`.

Use this query:

```promql
rknmon_dpi_check_status{agent=~"$agent", method=~"$method", target=~"$target"}
```

Legend:

```text
{{agent}} / {{target}} / {{method}}
```

Mappings:

- `1` → `ok`, green
- `0` → `fail`, red
- null/no data → gray if Grafana supports it

If `state-timeline` renders poorly in the local Grafana version, switch `type` to `status-history` and keep the same query/mappings.

- [ ] **Step 3: Run history test**

Run:

```bash
pytest -q tests/test_grafana_dpi_dashboard.py::test_dpi_dashboard_has_history_panels
```

Expected: PASS.

- [ ] **Step 4: Commit history panels**

```bash
git add grafana/dashboards/dpi.json
git commit -m "grafana: add DPI history panels"
```

---

## Task 6: Full validation and live Grafana check

**Files:**
- Read/validate: `grafana/dashboards/dpi.json`
- Test: `tests/test_grafana_dpi_dashboard.py`, existing test suite
- Runtime: Docker compose / Grafana API if containers are available

- [ ] **Step 1: Validate dashboard JSON**

Run:

```bash
python3 -m json.tool grafana/dashboards/dpi.json >/tmp/dpi-dashboard.json
```

Expected: exit code 0.

- [ ] **Step 2: Run DPI dashboard tests**

Run:

```bash
pytest -q tests/test_grafana_dpi_dashboard.py
```

Expected: all tests pass.

- [ ] **Step 3: Run all tests**

Run:

```bash
pytest -q
```

Expected: all tests pass.

- [ ] **Step 4: Check Git diff for accidental secrets or unrelated changes**

Run:

```bash
git diff --stat HEAD~5..HEAD
git diff --name-only HEAD~5..HEAD
```

Expected: only `grafana/dashboards/dpi.json`, `tests/test_grafana_dpi_dashboard.py`, and plan/spec docs changed.

- [ ] **Step 5: Reload Grafana provisioning if local/prod stack is available**

Run from `/home/www/projects/rkn-blocks-monitoring`:

```bash
sudo docker compose -f docker-compose.prod.yml up -d grafana
```

Expected: `rknmon_grafana` is up.

- [ ] **Step 6: Verify dashboard through Grafana API if container is available**

Run:

```bash
sudo docker exec rknmon_grafana sh -lc \
  'curl -fsS -u "$GF_SECURITY_ADMIN_USER:$GF_SECURITY_ADMIN_PASSWORD" http://127.0.0.1:3000/api/dashboards/uid/rknmon-dpi' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); dash=d["dashboard"]; print(dash["uid"], dash["title"], dash.get("timezone"), len(dash.get("panels", [])))'
```

Expected output contains:

```text
rknmon-dpi RKN DPI checks Asia/Omsk
```

The panel count should be at least 6.

- [ ] **Step 7: Commit final validation/doc adjustments if needed**

If Task 6 changed files, commit them:

```bash
git add grafana/dashboards/dpi.json tests/test_grafana_dpi_dashboard.py docs/superpowers/plans/2026-06-11-dpi-dashboard-clarity.md
 git commit -m "grafana: clarify DPI dashboard"
```

If no files changed in Task 6, do not create an empty commit.

---

## Plan self-review

- Spec coverage:
  - Operational KPI top row: Task 3.
  - Operator-friendly table: Task 4.
  - Diagnostic matrix/fallback table: Task 4.
  - Latency and status history: Task 5.
  - Variables `agent`, `method`, `target`: Task 2.
  - No backend/schema changes: enforced by file scope.
  - Verification through JSON, pytest, Grafana API: Task 6.

- Placeholder scan:
  - No unresolved placeholder markers and no vague “add appropriate handling” steps.
  - Grafana field-color details include an allowed fallback, not an unspecified placeholder.

- Type/name consistency:
  - Panel titles in tests match plan titles exactly.
  - Datasource UIDs match current provisioning/current dashboard: `PBFA97CFB590B2093`, `grafana-postgres`.
  - DB columns match `dpi_probe_results`: `checker`, `target`, `method`, `ok`, `latency_ms`, `http_status`, `error_type`, `checked_at`.
