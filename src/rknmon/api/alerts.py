from fastapi import APIRouter, Request
from rknmon.db import fetch
from rknmon.api.deps import limiter

router = APIRouter(prefix="/alerts", tags=["alerts"])

@router.get("/webhook")
@limiter.limit("100/minute")
async def webhook_config(request: Request):
    from rknmon.config.settings import settings
    return {
        "configured": bool(settings.alert_webhook_url),
        "url_masked": settings.alert_webhook_url[:20] + "..." if settings.alert_webhook_url else None,
    }
