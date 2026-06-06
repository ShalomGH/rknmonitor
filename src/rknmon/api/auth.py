from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from rknmon.config.settings import settings

EXEMPT_PATHS = {"/", "/health", "/metrics", "/openapi.json", "/docs", "/redoc", "/ui/dashboard", "/ui/dashboard_data"}
EXEMPT_PREFIXES = ("/ui/", "/static/")

class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Normalize empty string from root "/" after potential strip
        normalized = path.rstrip("/") if path != "/" else "/"
        if normalized in EXEMPT_PATHS or normalized.startswith(EXEMPT_PREFIXES):
            return await call_next(request)
        api_key = request.headers.get("X-API-Key")
        if not api_key or api_key != settings.api_key:
            return JSONResponse({"detail": "Forbidden: invalid or missing API key"}, status_code=403)
        return await call_next(request)
