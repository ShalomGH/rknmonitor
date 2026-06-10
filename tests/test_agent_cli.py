import pytest
from unittest.mock import AsyncMock, patch

from rknmon.agent.cli import main_async


@pytest.mark.asyncio
async def test_main_async_runs_one_cycle_when_once_flag_set():
    with patch("rknmon.agent.cli.AgentClient") as mock_client_cls, \
         patch("rknmon.agent.cli.run_probe_cycle", new_callable=AsyncMock) as mock_run:
        mock_client = mock_client_cls.return_value

        await main_async([
            "--central-api-url", "https://mon.example.com",
            "--node-api-key", "node-secret",
            "--once",
        ])

        mock_client_cls.assert_called_once_with(
            "https://mon.example.com",
            "node-secret",
            "rknmon-agent",
            agent_location=None,
            agent_provider=None,
            agent_version="0.1.0",
            public_ip=None,
        )
        mock_run.assert_awaited_once_with(mock_client)
