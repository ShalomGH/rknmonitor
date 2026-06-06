# RKN Blocks Monitoring — Implementation Plan v2.0

> Status: POST M0–M3 | M4–M6 pending  
> Based on codebase at `/home/www/projects/rkn-blocks-monitoring`  
> Actual: ~100 targets, 10-min probe interval, 14 tests passing

---

## 1. Current State (M0–M3 Complete)

### What Exists

| Milestone | Status | Key Deliverables |
|-----------|--------|------------------|
| M0 Foundation | DONE | Git repo, Docker Compose (dev), CI (GitHub Actions), `pyproject.toml`, `.venv` |
| M1 Probe Core | DONE | HTTP/HTTPS probe (`aiohttp`), DNS probe (`aiodns` 4.x), APScheduler (10-min interval, ±30s jitter), `asyncpg` pool, PostgreSQL 16 schema (`targets`, `probes`, `events`), self-monitoring (`/health`, `/metrics`) |
| M2 Target Management | DONE | CRUD REST API (`/targets`), CSV ingestor (`csv.DictReader` + `asyncpg`, no pandas), `ON CONFLICT` upsert, dedup by domain |
| M3 Detection & Events | DONE | Rule-based classifier (`clear`/`suspected`/`blocked`), state engine (emits `target_blocked`/`target_unblocked`/`state_changed`), evaluator/orchestrator, generic webhook alerting (VPN-safe) |

### Existing API Endpoints

```
GET  /               → app info
GET  /health         → liveness + DB connectivity
GET  /metrics        → Prometheus (http_requests_total, http_request_duration_seconds)
GET  /targets        → list targets
POST /targets        → create/upsert target
GET  /targets/{id}   → get target
PATCH /targets/{id}  → update target
DELETE /targets/{id} → delete target
GET  /events         → list events
GET  /probes/latest  → latest probes
GET  /probes/statistics → probe stats
GET  /alerts/webhook → webhook config status
```

### File Structure

```
src/rknmon/
  api/          — FastAPI routers (main, targets, events, probes, alerts)
  probes/       — http_probe, dns_probe, orchestrator, scheduler (APScheduler),
                  classifier, state_engine, evaluator
  alerts/       — webhook.py (generic async webhook sender)
  ingest/       — csv_loader.py (DictReader + asyncpg)
  models/       — Pydantic schemas (Target, ProbeResult, Event)
  config/       — pydantic-settings (env-based)
  db.py         — asyncpg pool wrapper
  db_schema.py  — init_schema() (CREATE TABLE IF NOT EXISTS)
tests/          — 14 tests (pytest, async)
scripts/        — ingest.py, probe.py, evaluate.py (CLI wrappers)
```

### Known Limitations (to Address in M4–M6)

- No HTML dashboard — only JSON API
- No export endpoints (CSV/JSON dump)
- No aggregate statistics endpoint
- No authentication — API is fully open
- No rate limiting
- No backup/restore scripts
- No production Docker Compose variant
- No load testing or performance validation
- No operational runbook

---

## 2. Remaining Milestones & Deliverables

### M4 — Dashboard & API Expansion (Week 7–8)

**Goal:** Deliver web dashboard and expand API surface for operators.

| # | Task | Deliverable | Est. |
|---|------|-------------|------|
| 4.1 | Stats endpoint | `GET /stats` — aggregate counts (targets, blocked, suspected, probes 24h, events 24h) | 30 min |
| 4.2 | Export endpoints | `GET /export/targets?format=json|csv`, `GET /export/events?format=json|csv&hours=24` | 45 min |
| 4.3 | Dashboard UI | HTMX + Alpine.js + Chart.js dark-themed dashboard: stats cards, target list with search/filter, events table, auto-refresh every 30s | 2h |
| 4.4 | Target detail page | `/ui/target/{id}` — probe history + event timeline for single target | 30 min |

**Architecture Decision:**
- Dashboard served by same FastAPI process via Jinja2 templates.
- HTMX for server-rendered interactivity (no SPA build step, VPN-friendly).
- Alpine.js for lightweight client state (dropdowns, tabs).
- Chart.js for trends (blocked % over time, probe latency distribution).
- CDN links for JS libs (no npm/build); fallback to vendoring if VPN blocks CDNs.

**New Files:**
```
src/rknmon/api/stats.py
src/rknmon/api/export.py
src/rknmon/ui/dashboard.py
src/rknmon/ui/templates/base.html
src/rknmon/ui/templates/dashboard.html
src/rknmon/ui/templates/target_detail.html
tests/test_stats.py
tests/test_export.py
tests/test_ui.py
```

### M5 — Hardening & Ops (Week 9)

**Goal:** Production-ready security, deployment, and backup.

| # | Task | Deliverable | Est. |
|---|------|-------------|------|
| 5.1 | API-key auth | Starlette middleware: `X-API-Key` header or `?api_key=` query param. Skip `/health`, `/metrics`, `/` | 45 min |
| 5.2 | Rate limiting | `slowapi` per-IP rate limiting on heavy endpoints (`/stats`, `/export/*`) | 30 min |
| 5.3 | Backup script | `scripts/backup.py` — `pg_dump` + gzip, retention policy (default 7 days) | 30 min |
| 5.4 | Prod deployment | `docker-compose.prod.yml` (no volume mounts, multi-worker uvicorn, env validation), `docs/deployment.md` | 45 min |

**Architecture Decisions:**
- Auth: API-key only (no OAuth2) — internal VPN-only deployment, no external users.
- Rate limit: 30 req/min per IP on stats/export; dashboard HTML pages exempt (HTMX polling is lightweight).
- Backup: local filesystem (`/backups` mount), not S3 — system has no internet egress.

**New/Modified Files:**
```
src/rknmon/middleware/auth.py
src/rknmon/middleware/rate_limit.py
src/rknmon/config/settings.py      (+ api_key, rate_limit_rps)
scripts/backup.py
tests/test_auth.py
tests/test_rate_limit.py
tests/test_backup.py
docker-compose.prod.yml
docs/deployment.md
```

### M6 — Review & Stabilise (Week 10)

**Goal:** Validate performance, document operations, freeze v1.0.

| # | Task | Deliverable | Est. |
|---|------|-------------|------|
| 6.1 | Synthetic data generator | `scripts/generate_targets.py --count N` for load testing | 30 min |
| 6.2 | Load test | `scripts/load_test.py` (locustfile) — validate 1000+ targets, 50 concurrent users, p95 < 500ms | 1h |
| 6.3 | Runbook | `docs/runbook.md` — health checks, common issues, backup/restore, rollback | 30 min |
| 6.4 | Integration & tag | Full test suite + manual end-to-end, git tag `v1.0.0` | 1h |

**Acceptance Criteria:**
- pytest: all tests pass, coverage ≥ 70%
- locust: 50 users, 5 spawn/s, 5 min run → error rate < 1%, p95 latency < 500ms
- Manual: seed 1000 targets, verify dashboard renders, export downloads, auth blocks unauthorized requests

---

## 3. Proposed Architecture

### Tech Stack (Locked)

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Runtime | Python 3.12 | Existing, no migration needed |
| API Framework | FastAPI | Already in use, async native, OpenAPI auto-gen |
| DB | PostgreSQL 16 | Existing, `asyncpg` pool, partitioning-ready |
| Scheduler | APScheduler (in-process) | Simpler than Celery+Redis at 100-target scale; swap to Celery only if >10k targets or multi-node |
| Frontend | Jinja2 + HTMX + Alpine.js + Chart.js | Zero build step, minimal JS, works over slow VPN |
| Auth | API-key middleware (`secrets.compare_digest`) | Sufficient for internal-only deployment |
| Rate Limit | `slowapi` (Redis-backed in future if multi-node) | In-memory sufficient for single-node |
| Monitoring | Prometheus `/metrics` + `/health` | Existing, integrates with standard stacks |
| Alerting | Generic webhook (`POST` JSON to internal URL) | VPN-safe; no internet egress required |
| Deployment | Docker Compose (single node) | Matches current setup; Kubernetes only if scaling beyond 1 node |

### Scale Targets

| Metric | v1.0 (Current) | Ceiling (Future) |
|--------|---------------|------------------|
| Targets | ~100 | 200,000 (RKN dump) |
| Probe interval | 10 min | 5 min |
| Result rows/day | ~14.4k | ~57.6M |
| Peak req/s | ~0.17 | ~667 |
| Concurrency limit | 50 (asyncio Semaphore) | 100–200 |
| DB partitions | Not required | Daily `RANGE` on `checked_at` |

**Decision Point:** If target count grows beyond 10k, enable daily table partitioning and consider swapping APScheduler to Celery + Redis.

---

## 4. Data Models & APIs

### Database Schema (Existing)

```sql
-- targets
id SERIAL PRIMARY KEY,
url TEXT NOT NULL,
domain TEXT NOT NULL UNIQUE,
ip INET,
category TEXT,
source TEXT DEFAULT 'manual',
is_active BOOLEAN DEFAULT true,
state VARCHAR(10) DEFAULT 'clear',
created_at TIMESTAMPTZ DEFAULT now(),
updated_at TIMESTAMPTZ DEFAULT now()

-- probes
id SERIAL PRIMARY KEY,
target_id INTEGER REFERENCES targets(id) ON DELETE CASCADE,
probe_type VARCHAR(10) NOT NULL,
status_code INTEGER,
response_time_ms INTEGER,
body_hash TEXT,
error TEXT,
resolver TEXT,
result JSONB,
checked_at TIMESTAMPTZ DEFAULT now()

-- events
id BIGSERIAL PRIMARY KEY,
target_id INTEGER REFERENCES targets(id) ON DELETE CASCADE,
event_type VARCHAR(30) NOT NULL,
old_state VARCHAR(10),
new_state VARCHAR(10),
details JSONB,
created_at TIMESTAMPTZ DEFAULT now()
```

**Indexes:** `idx_probes_target_id`, `idx_probes_checked_at`, `idx_events_target_id`, `idx_events_created_at`.

### New API Endpoints (M4–M5)

```
GET  /stats                    → aggregate statistics (JSON)
GET  /export/targets           → download targets (JSON or CSV)
GET  /export/events            → download events (JSON or CSV)
GET  /ui                       → HTML dashboard page
GET  /ui/stats                 → dashboard stats fragment (JSON, HTMX)
GET  /ui/targets?q=&state=     → target list fragment (JSON, HTMX)
GET  /ui/events                → events fragment (JSON, HTMX)
GET  /ui/target/{id}           → target detail HTML page
```

### Authentication

- `API_KEY` env var enables middleware.
- Exempt: `/health`, `/metrics`, `/` (monitoring needs liveness).
- All other endpoints require `X-API-Key: <key>` header or `?api_key=<key>`.
- HTML requests with missing key → 401 HTML page; JSON requests → 401 JSON.

---

## 5. Monitoring & Alerting Requirements

### Self-Monitoring (Existing)

| Endpoint | Purpose | Consumer |
|----------|---------|----------|
| `GET /health` | Liveness + DB connectivity | Docker healthcheck, load balancer |
| `GET /metrics` | Prometheus: request count, latency histogram | Prometheus/Grafana |

### Alerting Rules (Existing Webhook)

| Condition | Event Type | Payload |
|-----------|------------|---------|
| Target state → `blocked` | `target_blocked` | `{event, target_id, old_state, new_state, details, timestamp}` |
| Target state → `clear` from `blocked` | `target_unblocked` | same |
| Any state change | `state_changed` | same |

**Constraint:** System has no internet egress. Webhook must target an internal URL (existing monitoring stack, PagerDuty on-prem, or VPN-exit relay). External bots (Telegram, Slack) require a proxy in DMZ.

### External Vantage Point (M3, Optional Enhancement)

- Small agent on out-of-RU VPS probes same target.
- If external = reachable AND internal = not reachable → auto `blocked`.
- Config: `EXTERNAL_VANTAGE_URL` + `EXTERNAL_VANTAGE_API_KEY`.
- **Decision Point:** Only implement if VPS is already available; otherwise defer to post-v1.0.

---

## 6. Testing Strategy

### Unit Tests (pytest)

| Component | Tests | Status |
|-----------|-------|--------|
| API (health, root) | `tests/test_api.py` | 2 tests, passing |
| Classifier | `tests/test_classifier.py` | passing |
| Probes (HTTP/DNS) | `tests/test_probes.py` | passing |
| Basic integration | `tests/test_basic.py` | passing |
| Stats | `tests/test_stats.py` | NEW (M4) |
| Export | `tests/test_export.py` | NEW (M4) |
| Auth | `tests/test_auth.py` | NEW (M5) |
| Rate limit | `tests/test_rate_limit.py` | NEW (M5) |
| Backup | `tests/test_backup.py` | NEW (M5, integration) |

### Load Tests (locust)

- File: `scripts/load_test.py`
- Scenarios: stats polling, target listing, event retrieval, export download, dashboard page load
- Target: 50 concurrent users, 5 spawn/s, 5 min → p95 < 500ms, error rate < 1%

### Performance Validation (M6)

1. Generate 1000 synthetic targets: `python scripts/generate_targets.py --count 1000`
2. Run locust against local instance.
3. Monitor DB CPU, connection pool saturation, memory.
4. If p95 > 500ms → profile `asyncpg` queries, add indexes, or tune pool size.

---

## 7. Estimated Effort & Risks

### Effort Breakdown

| Milestone | Tasks | Est. Effort |
|-----------|-------|-------------|
| M4 Dashboard & API | 4.1–4.4 | ~3.5h |
| M5 Hardening & Ops | 5.1–5.4 | ~2.5h |
| M6 Review & Stabilise | 6.1–6.4 | ~3h |
| **M4–M6 Total** | 11 tasks | **~9h** (1 dev, compact) |

**Note:** Estimates assume direct implementation by developer familiar with codebase. Review and iteration not included.

### Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| DNS probe flakes (NXDOMAIN false positives) | Medium | High alert noise | Multi-resolver consensus, retry with backoff, classifier tuning |
| APScheduler single-node bottleneck | Low | Medium | Documented swap path to Celery+Redis; Semaphore + batch INSERT already in place |
| HTMX CDN blocked by VPN | Low | Dashboard broken | Vendor JS libs into `src/rknmon/ui/static/` as fallback |
| `slowapi` in-memory limiter resets on restart | Low | Rate limit bypassed | Acceptable for v1.0 single-node; switch to Redis backend if multi-node |
| DB disk full on 1000+ targets with 10-min probes | Low | System down | Backup script + retention (`result_retention_days=90`); partitions if >10k |
| External vantage VPS unavailable | Medium | M3 feature incomplete | Mark as optional; auto-detect via config presence |

---

## 8. Open Decisions (To Close Before M4 Start)

1. **Dashboard access:** Will the dashboard be exposed beyond internal engineers? If yes, add basic auth form (/htpasswd-style) in addition to API key.
2. **CDN vs vendoring:** Should HTMX/Alpine.js/Chart.js be vendored into the repo for air-gapped VPN deployments? **Recommendation:** vendor to `src/rknmon/ui/static/` to eliminate external dependency.
3. **Alert webhook receiver:** What internal URL receives alerts? Need endpoint spec from ops team before configuring `ALERT_WEBHOOK_URL` in production.
4. **External vantage VPS:** Do we have an out-of-RU server ready? If not, skip M3 external vantage integration and document as v1.1 feature.

---

## 9. Task Index for Kanban

| ID | Task | Milestone | Assignee | Depends On |
|----|------|-----------|----------|------------|
| 4.1 | `GET /stats` aggregate endpoint | M4 | backend | — |
| 4.2 | `GET /export` CSV/JSON endpoints | M4 | backend | — |
| 4.3 | Dashboard HTML + HTMX + Alpine.js | M4 | backend | 4.1, 4.2 |
| 4.4 | Target detail page | M4 | backend | 4.3 |
| 5.1 | API-key auth middleware | M5 | backend | — |
| 5.2 | Rate limiting (`slowapi`) | M5 | backend | 5.1 |
| 5.3 | `pg_dump` backup script | M5 | backend | — |
| 5.4 | Production compose + deploy docs | M5 | backend | — |
| 6.1 | Synthetic target generator | M6 | backend | — |
| 6.2 | Locust load test | M6 | backend | 6.1 |
| 6.3 | Operational runbook | M6 | backend | — |
| 6.4 | Final integration + v1.0.0 tag | M6 | backend | ALL |

---

*Plan version: 2.0 | Status: Ready for implementation | M0–M3 baseline committed*  
*Last updated: 2026-06-06 | Next step: Close Open Decisions §8, then begin M4*
