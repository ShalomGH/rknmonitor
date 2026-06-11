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
    assert len(matches) == 1, f"Expected exactly one panel titled {title!r}"
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
    assert "label_values(rknmon_dpi_check_status, agent)" in str(
        variables["agent"]["query"]
    )
    assert variables["method"]["datasource"]["uid"] == PROM_UID
    assert "label_values(rknmon_dpi_check_status" in str(variables["method"]["query"])
    assert variables["target"]["datasource"]["uid"] == PROM_UID
    assert "label_values(rknmon_dpi_check_status" in str(variables["target"]["query"])


def test_dpi_dashboard_has_operational_kpi_row():
    dashboard = load_dashboard()

    expected = {
        "Overall DPI status": {
            "x": 0,
            "expr": 'sum(1 - rknmon_dpi_check_status{agent=~"$agent", method=~"$method", target=~"$target"})',
        },
        "Affected targets": {
            "x": 6,
            "expr": 'count(count by (target) (rknmon_dpi_check_status{agent=~"$agent", method=~"$method", target=~"$target"} == 0))',
        },
        "Affected agents": {
            "x": 12,
            "expr": 'count(count by (agent) (rknmon_dpi_check_status{agent=~"$agent", method=~"$method", target=~"$target"} == 0))',
        },
        "Latest failure age": {
            "x": 18,
            "expr": 'time() - max(timestamp(rknmon_dpi_check_status{agent=~"$agent", method=~"$method", target=~"$target"} == 0))',
        },
    }

    for title, spec in expected.items():
        panel = panel_by_title(dashboard, title)
        assert panel["type"] == "stat"
        assert panel["datasource"] == {"type": "prometheus", "uid": PROM_UID}
        assert panel["gridPos"] == {"h": 5, "w": 6, "x": spec["x"], "y": 0}
        assert panel["options"]["colorMode"] == "background"
        assert panel["targets"][0]["datasource"] == {"type": "prometheus", "uid": PROM_UID}
        assert panel["targets"][0]["expr"] == spec["expr"]

    overall_defaults = panel_by_title(dashboard, "Overall DPI status")["fieldConfig"][
        "defaults"
    ]
    assert [
        step["color"] for step in overall_defaults["thresholds"]["steps"]
    ] == ["green", "yellow", "red"]

    latest_defaults = panel_by_title(dashboard, "Latest failure age")["fieldConfig"][
        "defaults"
    ]
    assert latest_defaults["unit"] == "s"
    assert [
        (step["color"], step["value"])
        for step in latest_defaults["thresholds"]["steps"]
    ] == [("green", None), ("yellow", 300), ("red", 1800)]

    overall_mappings = panel_by_title(dashboard, "Overall DPI status")["fieldConfig"][
        "defaults"
    ]["mappings"]
    assert any(
        mapping.get("type") == "value" and mapping.get("options", {}).get("0", {}).get("text") == "OK"
        for mapping in overall_mappings
    )
    assert any(
        mapping.get("type") == "range"
        and mapping.get("options", {}).get("from") == 1
        and mapping.get("options", {}).get("to") == 2
        and mapping.get("options", {}).get("result", {}).get("text") == "Degraded"
        for mapping in overall_mappings
    )
    assert any(
        mapping.get("type") == "special"
        and mapping.get("options", {}).get("match") == "null"
        and mapping.get("options", {}).get("result", {}).get("text") == "No data"
        for mapping in overall_mappings
    )

    latest_mappings = panel_by_title(dashboard, "Latest failure age")["fieldConfig"][
        "defaults"
    ]["mappings"]
    assert any(
        mapping.get("type") == "special"
        and mapping.get("options", {}).get("match") == "null"
        and mapping.get("options", {}).get("result", {}).get("text") == "No data"
        for mapping in latest_mappings
    )


def test_dpi_dashboard_has_operator_table_from_postgres():
    dashboard = load_dashboard()
    panel = panel_by_title(dashboard, "What is happening")

    assert panel["type"] == "table"
    assert panel["datasource"]["uid"] == POSTGRES_UID
    sql = target_text(panel)
    assert "FROM dpi_probe_results" in sql
    assert "JOIN probe_nodes" in sql
    expected_columns = [
        "agent",
        "target",
        "method",
        "status",
        "latency_ms",
        "error_type",
        "http_status",
        "checked_at",
    ]
    for column in expected_columns:
        assert column in sql
    assert "ORDER BY" in sql
    assert "n.name IN (${agent:sqlstring})" in sql
    assert "d.method IN (${method:sqlstring})" in sql
    assert "d.target IN (${target:sqlstring})" in sql
    assert "~ ${agent:sqlstring}" not in sql
    assert "~ ${method:sqlstring}" not in sql
    assert "~ ${target:sqlstring}" not in sql


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
    assert "n.name IN (${agent:sqlstring})" in sql
    assert "d.method IN (${method:sqlstring})" in sql
    assert "d.target IN (${target:sqlstring})" in sql
    assert "~ ${agent:sqlstring}" not in sql
    assert "~ ${method:sqlstring}" not in sql
    assert "~ ${target:sqlstring}" not in sql


def test_dpi_dashboard_has_history_panels():
    dashboard = load_dashboard()

    latency = panel_by_title(dashboard, "DPI latency over time")
    assert latency["type"] == "timeseries"
    assert latency["datasource"]["uid"] == PROM_UID
    assert "rknmon_dpi_check_latency_ms" in target_text(latency)
    assert 'method=~"$method"' in target_text(latency)
    assert 'target=~"$target"' in target_text(latency)

    history = panel_by_title(dashboard, "DPI status history")
    assert history["type"] in {
        "state-timeline",
        "status-history",
        "timeseries",
        "table",
    }
    assert history["datasource"]["uid"] in {PROM_UID, POSTGRES_UID}
