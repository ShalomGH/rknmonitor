from __future__ import annotations
import logging
import asyncio
from typing import List
import aiohttp
from rknmon.config.settings import settings

logger = logging.getLogger(__name__)

async def send_alert(event: dict) -> None:
    """Fire generic webhook alert for an event."""
    webhook_url = settings.alert_webhook_url
    if not webhook_url:
        logger.debug("No webhook configured, skipping alert")
        return

    payload = {
        "event": event["event_type"],
        "target_id": event["target_id"],
        "old_state": event.get("old_state"),
        "new_state": event.get("new_state"),
        "details": event.get("details"),
        "timestamp": event.get("created_at"),
    }

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as resp:
                if resp.status >= 400:
                    body = await resp.text()
                    logger.warning(f"Webhook returned {resp.status}: {body[:200]}")
                else:
                    logger.info(f"Alert sent to webhook ({resp.status})")
    except Exception as e:
        logger.error(f"Failed to send alert: {e}")

async def batch_send(events: List[dict]) -> None:
    await asyncio.gather(*[send_alert(e) for e in events], return_exceptions=True)
