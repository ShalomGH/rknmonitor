import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASOURCE_FILE = ROOT / "grafana/provisioning/datasources/datasource.yml"
DASHBOARD_FILE = ROOT / "grafana/dashboards/rknmon.json"


def test_grafana_has_postgres_datasource_for_agent_views():
    text = DATASOURCE_FILE.read_text()
    assert "name: App-DB" in text
    assert "type: postgres" in text
    assert "url: db:5432" in text


def test_dashboard_contains_agents_table_panel():
    dashboard = json.loads(DASHBOARD_FILE.read_text())
    panels = dashboard["panels"]
    agent_panels = [p for p in panels if p.get("title") == "Agents"]

    assert agent_panels, "Expected an 'Agents' panel in Grafana dashboard"
    panel = agent_panels[0]
    assert panel["type"] == "table"
    assert panel["datasource"]["uid"] == "grafana-postgres"
    raw_sql = panel["targets"][0]["rawSql"]
    assert "FROM probe_nodes" in raw_sql
    assert "last_seen_at" in raw_sql
    assert "agent_version" in raw_sql
