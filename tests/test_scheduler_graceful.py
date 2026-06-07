import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import asyncio

from rknmon.probes.scheduler import probe_job, shutdown_scheduler, start_scheduler


@pytest.mark.asyncio
async def test_probe_job_no_targets():
    """probe_job handles empty target list gracefully and clears _active_probe."""
    with patch("rknmon.probes.scheduler.fetch", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = []
        await probe_job()
        # _active_probe should be None after probe_job finishes
        import rknmon.probes.scheduler as sm
        assert sm._active_probe is None


@pytest.mark.asyncio
async def test_shutdown_scheduler_graceful():
    """shutdown_scheduler cancels active probe and waits up to 60s."""
    async def slow_task():
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            pass

    with patch("rknmon.probes.scheduler.scheduler", MagicMock()) as mock_sched:
        import rknmon.probes.scheduler as sm
        sm._active_probe = asyncio.create_task(slow_task())

        await shutdown_scheduler()

        assert sm._active_probe.done() or sm._active_probe.cancelled()
        mock_sched.shutdown.assert_called_once_with(wait=False)
