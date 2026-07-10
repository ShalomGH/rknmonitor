from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from prometheus_client import Counter, Histogram, make_asgi_app
from slowapi.errors import RateLimitExceeded

from rknmon.api import agents, alerts, events, export, probes, stats, targets
from rknmon.api.agent_invites_routes import public_router as agent_bootstrap_router
from rknmon.api.agent_invites_routes import router as admin_agents_router
from rknmon.api.auth import APIKeyMiddleware
from rknmon.api.deps import limiter
from rknmon.custom_metrics import ensure_event_metric, set_active_targets, update_target_state_metrics
from rknmon.db import close_pool, fetch, get_pool
from rknmon.db_schema import init_schema
from rknmon.probes.scheduler import shutdown_scheduler, start_scheduler

REQUEST_COUNT = Counter("http_requests_total", "HTTP requests", ["method", "endpoint", "status"])
REQUEST_DURATION = Histogram("http_request_duration_seconds", "HTTP request duration", ["method", "endpoint"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
DEPLOY_DIR = BASE_DIR / "deploy"
PUBLIC_AGENT_COMPOSE = BASE_DIR / "docker-compose.agent.public.yml"


async def hydrate_metrics_from_db() -> None:
    active_row = await fetch("SELECT COUNT(*) AS n FROM targets WHERE is_active = true")
    set_active_targets(int(active_row[0]["n"]) if active_row else 0)

    state_rows = await fetch("SELECT state, COUNT(*) AS n FROM target_states GROUP BY state")
    update_target_state_metrics({r["state"]: r["n"] for r in state_rows})

    event_rows = await fetch("SELECT DISTINCT event_type FROM events")
    for row in event_rows:
        ensure_event_metric(row["event_type"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    await init_schema()
    await hydrate_metrics_from_db()
    start_scheduler()
    yield
    await shutdown_scheduler()
    await close_pool()


app = FastAPI(title="RKN Blocks Monitoring", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    lambda req, exc: JSONResponse({"detail": "Rate limit exceeded"}, status_code=429),
)
app.add_middleware(APIKeyMiddleware)

app.include_router(targets.router)
app.include_router(events.router)
app.include_router(alerts.router)
app.include_router(probes.router)
app.include_router(stats.router)
app.include_router(export.router)
app.include_router(agents.router)
app.include_router(admin_agents_router)
app.include_router(agent_bootstrap_router)

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


@app.get("/install-agent.sh", include_in_schema=False)
async def install_agent_script():
    return FileResponse(
        DEPLOY_DIR / "install-agent.sh",
        media_type="text/x-shellscript; charset=utf-8",
        filename="install-agent.sh",
    )


@app.get("/docker-compose.agent.public.yml", include_in_schema=False)
async def public_agent_compose():
    return FileResponse(
        PUBLIC_AGENT_COMPOSE,
        media_type="application/yaml; charset=utf-8",
        filename="docker-compose.agent.public.yml",
    )


@app.get("/")
async def root():
    return {"app": "rknmon", "version": "1.0.0"}
