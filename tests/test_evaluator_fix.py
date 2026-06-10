import pytest
from unittest.mock import AsyncMock, patch, MagicMock, call

from rknmon.probes.evaluator import evaluate_targets


@pytest.mark.asyncio
async def test_evaluate_all_targets_batched():
    """evaluate_targets fetches targets, nodes, latest http, and latest dns in flat queries."""
    target_rows = [
        {"id": 1, "domain": "example.com"},
        {"id": 2, "domain": "blocked.ru"},
    ]
    node_rows = [{"probe_node_id": 7}]
    http_rows = [
        {"target_id": 1, "probe_node_id": 7, "result": {"status_code": 200}},
        {"target_id": 2, "probe_node_id": 7, "result": {"status_code": None, "error": "timeout"}},
    ]
    dns_rows = [
        {"target_id": 1, "probe_node_id": 7, "result": {"results": [{"ip": "203.0.113.34"}]}},
    ]

    with patch("rknmon.probes.evaluator.fetch", new_callable=AsyncMock) as mock_fetch, \
         patch("rknmon.probes.evaluator.update_target_state", new_callable=AsyncMock) as mock_state, \
         patch("rknmon.probes.evaluator.refresh_target_state_metrics", new_callable=AsyncMock), \
         patch("rknmon.probes.evaluator.refresh_event_metric_labels", new_callable=AsyncMock), \
         patch("rknmon.probes.evaluator.batch_send", new_callable=AsyncMock):

        mock_fetch.side_effect = [target_rows, node_rows, http_rows, dns_rows]
        mock_state.return_value = None

        await evaluate_targets(target_ids=None)

        assert mock_fetch.call_count == 4
        calls = mock_fetch.call_args_list
        assert "targets" in calls[0][0][0].lower()
        assert "distinct probe_node_id" in calls[1][0][0].lower()
        assert "probe_type = 'http'" in calls[2][0][0]
        assert "probe_type = 'dns'" in calls[3][0][0]

        assert mock_state.call_count == 2


@pytest.mark.asyncio
async def test_evaluate_targets_filter_by_ids():
    """evaluate_targets respects target_ids filter."""
    with patch("rknmon.probes.evaluator.fetch", new_callable=AsyncMock) as mock_fetch, \
         patch("rknmon.probes.evaluator.update_target_state", new_callable=AsyncMock) as mock_state, \
         patch("rknmon.probes.evaluator.refresh_target_state_metrics", new_callable=AsyncMock), \
         patch("rknmon.probes.evaluator.refresh_event_metric_labels", new_callable=AsyncMock), \
         patch("rknmon.probes.evaluator.batch_send", new_callable=AsyncMock):

        mock_fetch.side_effect = [[{"id": 5, "domain": "a.com"}], [{"probe_node_id": 7}], [], []]
        mock_state.return_value = None

        await evaluate_targets(target_ids=[5])

        assert mock_fetch.call_count == 4
        assert "targets WHERE is_active = true AND id = any($1)" in mock_fetch.call_args_list[0][0][0]


@pytest.mark.asyncio
async def test_evaluate_empty_targets():
    """evaluate_targets returns empty list when no active targets exist."""
    with patch("rknmon.probes.evaluator.fetch", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = []
        result = await evaluate_targets()
        assert result == []
        assert mock_fetch.call_count == 1
