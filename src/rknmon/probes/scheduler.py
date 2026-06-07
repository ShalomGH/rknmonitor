from __future__ import annotations
import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from rknmon.config.settings import settings
from rknmon.db import fetch
from rknmon.probes.orchestrator import run_all
from rknmon.probes.cleanup import cleanup_old_records

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
_active_probe: asyncio.Task | None = None

async def probe_job():
    global _active_probe
    logger.info("Starting scheduled probe run")
    rows = await fetch(
        "SELECT id, url, domain FROM targets WHERE is_active = true"
    )
    targets = [dict(r) for r in rows]
    if not targets:
        logger.warning("No active targets to probe")
        return
    _active_probe = asyncio.create_task(run_all(targets))
    try:
        await _active_probe
    except asyncio.CancelledError:
        logger.warning("Active probe run was cancelled during shutdown")
    finally:
        _active_probe = None
    logger.info(f"Probed {len(targets)} targets")

async def cleanup_job():
    try:
        result = await cleanup_old_records()
        logger.info(f"Scheduled cleanup: {result}")
    except Exception:
        logger.exception("Scheduled cleanup failed")

def start_scheduler(loop=None):
    trigger = IntervalTrigger(
        minutes=settings.probe_interval_minutes,
        jitter=settings.probe_jitter_seconds,
    )
    scheduler.add_job(probe_job, trigger=trigger, id="probe_run", replace_existing=True)
    scheduler.add_job(
        cleanup_job,
        trigger=CronTrigger(hour=3, minute=0),
        id="cleanup",
        replace_existing=True,
    )
    if loop:
        scheduler.configure(event_loop=loop)
    scheduler.start()
    logger.info(f"Scheduler started with {settings.probe_interval_minutes}min interval")

async def shutdown_scheduler():
    """Graceful shutdown: cancel active probe if any, then stop scheduler."""
    logger.info("Shutting down scheduler...")
    if _active_probe and not _active_probe.done():
        _active_probe.cancel()
        try:
            await asyncio.wait_for(_active_probe, timeout=60)
        except asyncio.TimeoutError:
            logger.warning("Active probe did not finish within 60s, forcing shutdown")
        except asyncio.CancelledError:
            pass
    scheduler.shutdown(wait=False)
    logger.info("Scheduler shut down")
