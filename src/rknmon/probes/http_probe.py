import asyncio
import hashlib
import time
from typing import Optional
import aiohttp
import aiohttp.client_exceptions
from rknmon.config.settings import settings

async def probe_http(
    url: str,
    timeout: float = 30.0,
    follow_redirects: bool = True,
    session: Optional[aiohttp.ClientSession] = None,
) -> dict:
    close = False
    if session is None:
        timeout_obj = aiohttp.ClientTimeout(total=timeout)
        # Support corporate proxy via env var
        connector = None
        if settings.proxy_url:
            connector = aiohttp.TCPConnector()
        session = aiohttp.ClientSession(
            timeout=timeout_obj,
            connector=connector,
            trust_env=True,
        )
        close = True

    start = time.perf_counter()
    result = {
        "url": url,
        "reachable": False,
        "status_code": None,
        "response_time_ms": None,
        "body_hash": None,
        "redirect_url": None,
        "error": None,
        "headers": {},
    }

    try:
        proxy = settings.proxy_url
        async with session.get(url, allow_redirects=follow_redirects, proxy=proxy) as resp:
            elapsed = (time.perf_counter() - start) * 1000
            body = await resp.read()
            result.update({
                "reachable": True,
                "status_code": resp.status,
                "response_time_ms": round(elapsed, 2),
                "body_hash": hashlib.sha256(body).hexdigest()[:16],
                "headers": dict(resp.headers),
            })
            if resp.history:
                result["redirect_url"] = str(resp.url)
    except aiohttp.client_exceptions.ClientConnectorError as e:
        result["error"] = f"connection_error: {e.__class__.__name__}"
    except asyncio.TimeoutError:
        result["error"] = "timeout"
    except Exception as e:
        result["error"] = f"{e.__class__.__name__}: {str(e)[:200]}"
    finally:
        if close:
            await session.close()

    return result
