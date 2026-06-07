import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import asyncio

from rknmon.probes.cleanup import cleanup_old_records, parse_rowcount
from rknmon.config.settings import settings


class TestParseRowcount:
    def test_valid_delete(self):
        assert parse_rowcount("DELETE 42") == 42

    def test_zero(self):
        assert parse_rowcount("DELETE 0") == 0

    def test_none(self):
        assert parse_rowcount(None) == 0

    def test_empty(self):
        assert parse_rowcount("") == 0

    def test_garbage(self):
        assert parse_rowcount("foo bar") == 0


@pytest.mark.asyncio
async def test_cleanup_old_records():
    """Cleanup calls execute with proper intervals and returns counts."""
    with patch("rknmon.probes.cleanup.execute", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = "DELETE 3"
        result = await cleanup_old_records()

        assert result["probes_deleted_rowcount"] == 3
        assert result["events_deleted_rowcount"] == 3
        assert mock_exec.call_count == 2

        probe_sql = mock_exec.call_args_list[0][0][0]
        event_sql = mock_exec.call_args_list[1][0][0]
        assert "probes" in probe_sql
        assert "events" in event_sql
        assert str(settings.result_retention_days) in mock_exec.call_args_list[0][0][1]
        assert str(settings.event_retention_days) in mock_exec.call_args_list[1][0][1]
