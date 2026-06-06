from fastapi import APIRouter
from rknmon.db import fetch

router = APIRouter(prefix="/alerts", tags=["alerts"])

@router.get("/webhook")
async def webhook_config():
    from rknmon.config.settings import settings
    return {
        "configured": bool(settings.alert_webhook_url),
        "url_masked": settings.alert_webhook_url[:20] + "..." if settings.alert_webhook_url else None,
    }
