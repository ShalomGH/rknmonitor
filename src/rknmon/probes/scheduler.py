from __future__ import annotations
import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from rknmon.config.settings import settings
from rknmon.db import fetch
from rknmon.probes.orchestrator import run_all

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

async def probe_job():
    logger.info("Starting scheduled probe run")
    rows = await fetch(
        "SELECT id, url, domain FROM targets WHERE is_active = true"
    )
    targets = [dict(r) for r in rows]
    if not targets:
        logger.warning("No active targets to probe")
        return
    await run_all(targets)
    logger.info(f"Probed {len(targets)} targets")

def start_scheduler(loop=None):
    trigger = IntervalTrigger(
        minutes=settings.probe_interval_minutes,
        jitter=settings.probe_jitter_seconds,
    )
    scheduler.add_job(probe_job, trigger=trigger, id="probe_run", replace_existing=True)
    if loop:
        scheduler.configure(event_loop=loop)
    scheduler.start()
    logger.info(f"Scheduler started with {settings.probe_interval_minutes}min interval")

def shutdown_scheduler():
    scheduler.shutdown(wait=False)
    logger.info("Scheduler shut down")
