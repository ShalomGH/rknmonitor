from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from prometheus_client import make_asgi_app, Counter, Histogram
from slowapi.errors import RateLimitExceeded
from rknmon.custom_metrics import ensure_event_metric, set_active_targets
from rknmon.db import get_pool, close_pool, fetch
from rknmon.db_schema import init_schema
from rknmon.probes.scheduler import start_scheduler, shutdown_scheduler
from rknmon.probes.state_engine import refresh_target_state_metrics
from rknmon.api import targets, events, alerts, probes, stats, export, agents
from rknmon.api.agent_invites_routes import public_router as agent_bootstrap_router
from rknmon.api.agent_invites_routes import router as admin_agents_router
from rknmon.api.auth import APIKeyMiddleware
from rknmon.api.deps import limiter

REQUEST_COUNT = Counter("http_requests_total", "HTTP requests", ["method", "endpoint", "status"])
REQUEST_DURATION = Histogram("http_request_duration_seconds", "HTTP request duration", ["method", "endpoint"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
DEPLOY_DIR = BASE_DIR / "deploy"
PUBLIC_AGENT_COMPOSE = BASE_DIR / "docker-compose.agent.public.yml"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


async def hydrate_metrics_from_db() -> None:
    active_row = await fetch("SELECT COUNT(*) AS n FROM targets WHERE is_active = true")
    set_active_targets(int(active_row[0]["n"]) if active_row else 0)

    # Use the same role-aware aggregation as runtime updates. Otherwise a restart
    # would temporarily restore the old "worst state across every role" semantics.
    await refresh_target_state_metrics()

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
app.add_exception_handler(RateLimitExceeded, lambda req, exc: JSONResponse({"detail": "Rate limit exceeded"}, status_code=429))
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

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

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

@app.get("/ui/dashboard")
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {})

@app.get("/ui/target/{target_id}")
async def target_detail(request: Request, target_id: int):
    from rknmon.db import fetchrow, fetch
    target = await fetchrow("SELECT * FROM targets WHERE id = $1", target_id)
    if not target:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Target not found")
    probes_rows = await fetch(
        "SELECT * FROM probes WHERE target_id = $1 ORDER BY checked_at DESC LIMIT 50",
        target_id,
    )
    events_rows = await fetch(
        "SELECT * FROM events WHERE target_id = $1 ORDER BY created_at DESC LIMIT 50",
        target_id,
    )
    return templates.TemplateResponse(
        request,
        "target_detail.html",
        {
            "target": dict(target),
            "probes": [dict(r) for r in probes_rows],
            "events": [dict(r) for r in events_rows],
        },
    )


def _json_default(obj):
    from datetime import datetime
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError

@app.get("/ui/dashboard_data")
async def dashboard_data():
    from rknmon.db import fetch
    targets_rows = await fetch(
        "SELECT id, domain, state, category, is_active FROM targets WHERE is_active = true ORDER BY id"
    )
    by_state = await fetch(
        "SELECT state, COUNT(*) AS n FROM targets GROUP BY state"
    )
    events_24h = await fetch(
        """
        SELECT e.event_type, COUNT(*) AS n
        FROM events e
        WHERE e.created_at > now() - interval '24 hours'
        GROUP BY e.event_type
        """
    )
    daily_events = await fetch(
        """
        SELECT DATE(created_at) AS day, event_type, COUNT(*) AS n
        FROM events
        WHERE created_at > now() - interval '14 days'
        GROUP BY DATE(created_at), event_type
        ORDER BY day
        """
    )
    latest_probes = await fetch(
        """
        SELECT DISTINCT ON (target_id) p.*, t.domain
        FROM probes p JOIN targets t ON t.id = p.target_id
        ORDER BY target_id, checked_at DESC
        """
    )
    return {
        "targets": [dict(r) for r in targets_rows],
        "by_state": {r["state"]: r["n"] for r in by_state},
        "events_24h": {r["event_type"]: r["n"] for r in events_24h},
        "daily_events": [dict(r) for r in daily_events],
        "latest_probes": [dict(r) for r in latest_probes],
    }
