from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from prometheus_client import generate_latest

from rknmon.custom_metrics import (
    AGENT_LAST_SEEN_TIMESTAMP_GAUGE,
    BLOCKING_HYPOTHESIS_GAUGE,
    PROBE_LAST_COMPLETED_TIMESTAMP_GAUGE,
    PROBE_LAST_SUCCESS_TIMESTAMP_GAUGE,
    PROBE_LATENCY_GAUGE,
    prune_blocking_hypothesis_metrics,
    record_agent_seen,
    record_dpi_probe,
    record_probe_latency,
    record_probe_result,
)
from rknmon.probes.evaluator import evaluate_targets
from rknmon.probes.state_engine import _update_state_counts


def _metric_text(metric) -> str:
    return generate_latest(metric).decode()


def test_probe_latency_isolated_by_agent():
    record_probe_latency("edge-a-latency-test", "42", "example.com", "http", 123.0)
    record_probe_latency("edge-b-latency-test", "42", "example.com", "http", 456.0)

    text = _metric_text(PROBE_LATENCY_GAUGE)
    assert 'agent="edge-a-latency-test"' in text
    assert 'agent="edge-b-latency-test"' in text


def test_freshness_metrics_track_agent_activity_and_probe_completion():
    record_agent_seen("edge-freshness-test", "subject", timestamp=1234.0)
    before = datetime.now(timezone.utc).timestamp()

    record_probe_result(
        agent="edge-freshness-test",
        target_id="42",
        domain="example.com",
        probe_type="http",
        status_code=200,
        error=None,
        result={"reachable": True},
        response_time_ms=10.0,
    )

    agent_text = _metric_text(AGENT_LAST_SEEN_TIMESTAMP_GAUGE)
    completed_text = _metric_text(PROBE_LAST_COMPLETED_TIMESTAMP_GAUGE)
    success_text = _metric_text(PROBE_LAST_SUCCESS_TIMESTAMP_GAUGE)

    assert 'agent="edge-freshness-test",role="subject"} 1234.0' in agent_text
    assert 'agent="edge-freshness-test",probe_type="http"' in completed_text
    assert 'agent="edge-freshness-test",probe_type="http"' in success_text

    completed_sample = next(
        sample.value
        for metric in PROBE_LAST_COMPLETED_TIMESTAMP_GAUGE.collect()
        for sample in metric.samples
        if sample.labels == {"agent": "edge-freshness-test", "probe_type": "http"}
    )
    assert completed_sample >= before


def test_stale_blocking_hypothesis_is_pruned_after_next_cycle():
    agent = "edge-hypothesis-prune-test"
    label = record_dpi_probe(
        agent=agent,
        checker="mechanism-inference",
        target="example.com",
        method="sni_filter",
        ok=False,
        latency_ms=None,
        error_type="sni_filter",
        details={
            "experiment_type": "mechanism-inference",
            "hypothesis": "sni_filter",
            "confidence": 0.88,
        },
    )
    assert label is not None
    prune_blocking_hypothesis_metrics(agent, {label})
    assert f'agent="{agent}"' in _metric_text(BLOCKING_HYPOTHESIS_GAUGE)

    prune_blocking_hypothesis_metrics(agent, set())
    assert f'agent="{agent}"' not in _metric_text(BLOCKING_HYPOTHESIS_GAUGE)


@pytest.mark.asyncio
async def test_subject_failure_is_blocked_when_fresh_control_succeeds():
    now = datetime.now(timezone.utc)
    target_rows = [{"id": 1, "domain": "example.com"}]
    node_rows = [
        {"probe_node_id": 7, "role": "subject", "name": "isp-under-test"},
        {"probe_node_id": 9, "role": "control", "name": "control-vps"},
    ]
    http_rows = [
        {
            "target_id": 1,
            "probe_node_id": 7,
            "result": {"reachable": False, "error": "timeout"},
            "checked_at": now,
        },
        {
            "target_id": 1,
            "probe_node_id": 9,
            "result": {"reachable": True, "status_code": 200},
            "checked_at": now - timedelta(seconds=5),
        },
    ]
    dns_rows = [
        {"target_id": 1, "probe_node_id": 7, "result": {"tampered": False, "results": []}},
        {"target_id": 1, "probe_node_id": 9, "result": {"tampered": False, "results": []}},
    ]

    with patch("rknmon.probes.evaluator.fetch", new_callable=AsyncMock) as mock_fetch, \
         patch("rknmon.probes.evaluator.update_target_state", new_callable=AsyncMock) as mock_state, \
         patch("rknmon.probes.evaluator.refresh_target_state_metrics", new_callable=AsyncMock), \
         patch("rknmon.probes.evaluator.refresh_event_metric_labels", new_callable=AsyncMock), \
         patch("rknmon.probes.evaluator.batch_send", new_callable=AsyncMock):
        mock_fetch.side_effect = [target_rows, node_rows, http_rows, dns_rows]
        mock_state.return_value = None

        await evaluate_targets([1])

    subject_call = mock_state.await_args_list[0].args
    assert subject_call[0:3] == (1, 7, "blocked")
    assert subject_call[3]["external_vantage"] == "reachable_while_internal_not"
    comparison = subject_call[3]["vantage_comparison"]
    assert comparison["any_comparison_reachable"] is True
    assert comparison["matched"][0]["role"] == "control"


@pytest.mark.asyncio
async def test_stale_control_result_does_not_confirm_blocking():
    now = datetime.now(timezone.utc)
    target_rows = [{"id": 1, "domain": "example.com"}]
    node_rows = [
        {"probe_node_id": 7, "role": "subject", "name": "isp-under-test"},
        {"probe_node_id": 9, "role": "control", "name": "control-vps"},
    ]
    http_rows = [
        {
            "target_id": 1,
            "probe_node_id": 7,
            "result": {"reachable": False, "error": "timeout"},
            "checked_at": now,
        },
        {
            "target_id": 1,
            "probe_node_id": 9,
            "result": {"reachable": True, "status_code": 200},
            "checked_at": now - timedelta(hours=1),
        },
    ]
    dns_rows = [
        {"target_id": 1, "probe_node_id": 7, "result": {"tampered": False, "results": []}},
        {"target_id": 1, "probe_node_id": 9, "result": {"tampered": False, "results": []}},
    ]

    with patch.dict("os.environ", {"VANTAGE_MATCH_WINDOW_SECONDS": "300"}), \
         patch("rknmon.probes.evaluator.fetch", new_callable=AsyncMock) as mock_fetch, \
         patch("rknmon.probes.evaluator.update_target_state", new_callable=AsyncMock) as mock_state, \
         patch("rknmon.probes.evaluator.refresh_target_state_metrics", new_callable=AsyncMock), \
         patch("rknmon.probes.evaluator.refresh_event_metric_labels", new_callable=AsyncMock), \
         patch("rknmon.probes.evaluator.batch_send", new_callable=AsyncMock):
        mock_fetch.side_effect = [target_rows, node_rows, http_rows, dns_rows]
        mock_state.return_value = None

        await evaluate_targets([1])

    subject_call = mock_state.await_args_list[0].args
    assert subject_call[0:3] == (1, 7, "suspected")
    assert "external_vantage" not in subject_call[3]
    assert "vantage_comparison" not in subject_call[3]


@pytest.mark.asyncio
async def test_global_state_query_prefers_subject_roles():
    node_rows = [{"state": "blocked", "n": 1}]
    global_rows = [{"state": "clear", "n": 1}]

    with patch("rknmon.db.fetch", new_callable=AsyncMock) as mock_fetch, \
         patch("rknmon.probes.state_engine.update_target_state_metrics") as mock_update:
        mock_fetch.side_effect = [node_rows, global_rows]
        await _update_state_counts()

    global_sql = mock_fetch.await_args_list[1].args[0]
    assert "FILTER (WHERE role = 'subject')" in global_sql
    assert "LEFT JOIN probe_nodes" in global_sql
    mock_update.assert_called_once_with(
        {"clear": 1},
        {"blocked": 1},
    )
