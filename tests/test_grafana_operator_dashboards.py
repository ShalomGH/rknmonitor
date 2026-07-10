import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PROM_UID = "PBFA97CFB590B2093"


def load_dashboard(name: str) -> dict:
    return json.loads((ROOT / "grafana" / "dashboards" / name).read_text())


def panel_by_title(dashboard: dict, title: str) -> dict:
    matches = [panel for panel in dashboard["panels"] if panel.get("title") == title]
    assert len(matches) == 1, f"Expected one panel {title!r}, got {len(matches)}"
    return matches[0]


def expressions(panel: dict) -> str:
    return "\n".join(target.get("expr", "") for target in panel.get("targets", []))


def test_overview_counts_failed_statuses_instead_of_summing_zero_values():
    dashboard = load_dashboard("rknmon-overview.json")

    dpi = panel_by_title(dashboard, "Текущие DPI-сбои — по checker")
    xray = panel_by_title(dashboard, "Текущие Xray-сбои — комбинации")
    agents = panel_by_title(dashboard, "Где проблема — по агентам")

    assert 'count by (checker) (rknmon_dpi_check_status{agent=~"$agent"} == 0)' in expressions(dpi)
    assert 'count by (protocol,transport,security) (rknmon_xray_profile_status{agent=~"$agent"} == 0)' in expressions(xray)
    assert "sum by" not in expressions(dpi)
    assert "sum by" not in expressions(xray)
    assert 'count by (agent) (rknmon_probe_status{agent=~"$agent",domain=~"$domain",probe_type=~"$probe_type"} == 0)' in expressions(agents)


def test_hypothesis_is_a_score_not_a_percentage_or_probability():
    dashboard = load_dashboard("rknmon-overview.json")
    panel = panel_by_title(dashboard, "Гипотеза механизма — балл 0–1")

    assert panel["datasource"] == {"type": "prometheus", "uid": PROM_UID}
    assert panel["fieldConfig"]["defaults"]["unit"] == "short"
    assert "не вероятность" in panel["description"].lower()
    assert "timestamp(" in expressions(panel)


def test_overview_uses_real_dpi_latency_when_controlled_experiments_are_disabled():
    dashboard = load_dashboard("rknmon-overview.json")
    panel = panel_by_title(dashboard, "Задержка DPI-checks — худшая за 15 минут")

    assert panel["type"] == "timeseries"
    assert panel["fieldConfig"]["defaults"]["unit"] == "ms"
    assert "max_over_time(rknmon_dpi_check_latency_ms" in expressions(panel)
    assert "rknmon_probe_stage_duration_seconds" not in expressions(panel)


def test_diagnostics_counts_failed_statuses_and_labels_score_honestly():
    dashboard = load_dashboard("rknmon-blocking-diagnostics.json")

    dpi = panel_by_title(dashboard, "Текущие провалы — checker / method")
    xray = panel_by_title(dashboard, "Неуспешные Xray-комбинации")
    score = panel_by_title(dashboard, "Макс. балл гипотезы — 0–1")

    assert 'count by (checker,method) (rknmon_dpi_check_status{agent=~"$agent",checker=~"$checker"} == 0)' in expressions(dpi)
    assert 'count by (protocol,transport,security) (rknmon_xray_profile_status{agent=~"$agent"} == 0)' in expressions(xray)
    assert score["fieldConfig"]["defaults"]["unit"] == "short"
    assert "не вероятность" in score["description"].lower()
