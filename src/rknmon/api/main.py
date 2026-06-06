from contextlib import asynccontextmanager
from fastapi import FastAPI
from prometheus_client import make_asgi_app, Counter, Histogram
from rknmon.db import get_pool, close_pool
from rknmon.db_schema import init_schema
from rknmon.probes.scheduler import start_scheduler, shutdown_scheduler
from rknmon.api import targets, events, alerts, probes

REQUEST_COUNT = Counter("http_requests_total", "HTTP requests", ["method", "endpoint", "status"])
REQUEST_DURATION = Histogram("http_request_duration_seconds", "HTTP request duration", ["method", "endpoint"])

@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    await init_schema()
    start_scheduler()
    yield
    shutdown_scheduler()
    await close_pool()

app = FastAPI(title="RKN Blocks Monitoring", version="0.1.0", lifespan=lifespan)
app.include_router(targets.router)
app.include_router(events.router)
app.include_router(alerts.router)
app.include_router(probes.router)

prom_app = make_asgi_app()
app.mount("/metrics", prom_app)

@app.get("/health")
async def health():
    try:
        pool = await get_pool()
        await pool.fetchval("SELECT 1")
        return {"status": "ok", "db": "ok"}
    except Exception as e:
        return {"status": "error", "db": str(e)}

@app.get("/")
async def root():
    return {"app": "rknmon", "version": "0.1.0"}
