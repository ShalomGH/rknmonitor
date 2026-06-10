import pytest
from unittest.mock import AsyncMock, patch

from rknmon.probes.evaluator import evaluate_targets
from rknmon.probes.state_engine import update_target_state


@pytest.mark.asyncio
async def test_evaluate_targets_runs_per_probe_node():
    target_rows = [{"id": 1, "domain": "youtube.com"}]
    node_rows = [{"probe_node_id": 7}, {"probe_node_id": 9}]
    http_rows = [
        {"target_id": 1, "probe_node_id": 7, "result": {"status_code": None, "error": "timeout"}},
        {"target_id": 1, "probe_node_id": 9, "result": {"status_code": 200}},
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

        assert mock_fetch.call_count == 4
        assert mock_state.await_count == 2
        first = mock_state.await_args_list[0].args
        second = mock_state.await_args_list[1].args
        assert first[0:2] == (1, 7)
        assert second[0:2] == (1, 9)
        assert first[2] == "suspected"
        assert second[2] == "clear"


@pytest.mark.asyncio
async def test_update_target_state_persists_per_probe_node():
    with patch("rknmon.probes.state_engine.fetchrow", new_callable=AsyncMock) as mock_fetchrow, \
         patch("rknmon.probes.state_engine.execute", new_callable=AsyncMock) as mock_execute, \
         patch("rknmon.probes.state_engine.record_event"), \
         patch("rknmon.probes.state_engine._update_state_counts", new_callable=AsyncMock):
        mock_fetchrow.side_effect = [None, {"id": 1, "target_id": 1, "event_type": "target_blocked"}]

        await update_target_state(1, 7, "blocked", {"http_timeout": True})

        select_sql = mock_fetchrow.await_args_list[0].args[0]
        insert_sql = mock_execute.await_args_list[0].args[0]
        assert "FROM target_states" in select_sql
        assert "INSERT INTO target_states" in insert_sql
        assert "probe_node_id" in insert_sql
