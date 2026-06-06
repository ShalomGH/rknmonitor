# RKN Blocks Monitoring — Implementation Plan

## 1. Current State Summary

No codebase or infrastructure exists yet. The project is at the ideation stage. Goal: build a system that monitors which domains/IPs are blocked by Roskomnadzor (RKN) and provides historical data, alerts, and a dashboard. The system must be deployable inside a corporate VPN without direct internet exposure.

## 2. Concrete Milestones

### M0 — Foundation (Week 1)
- [ ] Bootstrap repo, linting, CI stub, Docker Compose dev env.
- [ ] Choose and lock tech stack (see §4).

### M1 — Probe Core (Weeks 2–3)
- [ ] HTTP/HTTPS probe service: checks target URL reachability (status, body hash, headers, TLS cert info).
- [ ] DNS probe service: resolves target via multiple upstreams (system, Google, Cloudflare, Quad9), compares answers.
- [ ] Probe schedulers (APScheduler): configurable interval per target, jitter, backoff on failure.
- [ ] PostgreSQL schema: targets, probes, results, events. Indexes on `checked_at`, `target_id`.
- [ ] **Self-monitoring**: `/health` (liveness + DB connectivity) and `/metrics` (Prometheus-compatible).

Scalable design patterns retained: concurrency guard (asyncio Semaphore) and batch INSERT are still built in, but not required at this scale. DB partitioning (`RANGE` by `checked_at`) is also designed-in for future scaling but not mandatory in v1.0.

### M2 — Target Management (Week 4)
- [ ] Ingest official RKN blocklist or curated list (~100 priority domains). Deduplicate, normalise domains/IPs/subnets. **Use `csv.DictReader` + `asyncpg` batch insert (no pandas).**
- [ ] Admin UI / CLI to add custom targets, pause/resume monitoring, tag targets.
- [ ] Track target metadata: first-seen, last-seen, category, source.
- [ ] **Target sizing locked**: ~100 domains, 10-minute probe interval (see §7 Q3).

### M3 — Detection Logic, Events & External Vantage (Weeks 5–6)
- [ ] Blockage classifier: scores a target as `clear`, `suspected`, `blocked` based on probe results (HTTP timeout + DNS tampering + cert mismatch).
- [ ] Event log: every state transition generates an immutable event (`target_blocked`, `target_unblocked`, `probe_failed`).
- [ ] **External vantage point**: small agent on an out-of-RU VPS probes same target. Reachable externally but not internally = confirmed `blocked`.
- [ ] **Alerting**: generic webhook endpoint `/alerts/outgoing` for internal channels (VPN-safe). Optional proxy egress for external bots (Telegram, Slack).

### M4 — Dashboard & API (Weeks 7–8)
- [ ] REST API (FastAPI): targets, results, events, statistics.
- [ ] Web dashboard: HTMX + Alpine.js + Chart.js (minimal JS, fast iteration, VPN-friendly).
- [ ] Export: CSV/JSON dump of current blocklist, per-period diff.

### M5 — Hardening & Ops (Week 9)
- [ ] VPN-only deployment docs, systemd/Docker Compose production setup.
- [ ] Rate-limiting, basic auth / API keys.
- [ ] Backup strategy for DB and historical dumps.

### M6 — Review & Stabilise (Week 10)
- [ ] Performance test with 1000+ targets.
- [ ] Fix bugs, write runbook, freeze v1.0.

## 3. Technical Approach for Monitoring Blockages

| Signal | Technique | Blockage Indicator |
|---|---|---|
| **HTTP(S) reachability** | HEAD/GET from probe node; compare status, body hash, redirect chain | Timeout, reset, 451/403 forbidden pattern, body mismatch |
| **DNS resolution** | Resolve via multiple resolvers in parallel | NXDOMAIN, IP from known block page pool, empty answer |
| **TLS certificate** | Fetch cert chain, compare fingerprint against known good | Cert mismatch, handshake reset |
| **Traceroute** | Lightweight ICMP/TCP traceroute to target IP | Drop at ISP boundary hops |
| **External vantage** | Small agent on outside-RU VPS probes same target | Reachable externally but not internally = confirmed block |

Scoring algorithm (rule-based first, ML later if needed):
1. DNS returns block-page IP or NXDOMAIN → +2 suspicion.
2. HTTP times out or returns block-page body pattern → +2 suspicion.
3. TLS handshake blocked → +1 suspicion.
4. External vantage reachable while internal not → automatic `blocked`.

Thresholds configurable per target group.

## 4. Required Components / Services

| Layer | Component | Suggested Tool | Purpose |
|---|---|---|---|
| **Probe Workers** | Async HTTP/DNS probes | Python + asyncio/aiohttp + aiodns | Parallel, non-blocking checks |
| **Task Queue** | Scheduled probe dispatch | APScheduler (in-process, no broker) | Interval management, retry, jitter |
| **Backend API** | REST | FastAPI + Pydantic | Dashboard & integration API |
| **Database** | Relational store | PostgreSQL 16 (prod), SQLite (dev) | Targets, results, events |
| **Cache** | Rate-limit, pub-sub | Redis (optional, for API caching) | No longer required for Celery |
| **Dashboard** | Frontend | HTMX + Alpine.js + Chart.js | Minimal JS, fast iteration |
| **Alerting** | Notifications | Generic webhooks + optional proxy egress | VPN-safe alerting |
| **Ingestion** | RKN dump parser | Python `csv.DictReader` + `asyncpg` batch insert | Memory-efficient daily import |
| **Reverse Proxy** | TLS termination, auth | Nginx / Caddy | API + dashboard serving |
| **Deployment** | Containers + orchestration | Docker Compose (prod = single node) | Easy VPN-local deploy |

## 5. Throughput & Scaling Design

| Metric | v1.0 Value | Scaling Ceiling (future) | Notes |
|---|---|---|---|
| Max targets | **~100** | 200,000 | Curated priority list for v1.0 |
| Probe interval | **10 minutes** | 5 minutes | Jitter ±30s to avoid thundering herd |
| Result rows/day | **~14.4 k** | ~57.6 M | 100 × 6 probes/hour × 24h |
| Peak req/s | **~0.17** | ~667 | Negligible load at v1.0 scale |
| Concurrency limit | 50 concurrent probes | 100–200 | Semaphore in asyncio worker; tunable |
| DB writes | Batch INSERT every 1,000 results | Same | Or 1 second, whichever comes first |
| DB partitions | **Not required in v1.0** | Daily `RANGE` on `checked_at` | Designed-in, enabled when >10k targets |
| Retention | 90 days results, 1 year events | Configurable | Old partitions detached/dropped |

> **Why generic webhook for VPN?** The system deploys inside a corporate VPN with no internet egress. A Telegram bot cannot reach api.telegram.org from there. The `/alerts/outgoing` webhook fires JSON payloads to an internal URL (e.g., your existing monitoring stack, PagerDuty on-prem, or a custom relay). If external bots are needed later, add a tiny proxy service in a DMZ or use a VPN exit node — but the core system stays fully internal.

## 6. Estimated Effort

| Milestone | Effort | Notes |
|---|---|---|
| M0 Foundation | 1 dev-week | Repo, CI, dev-env |
| M1 Probe Core | 2 dev-weeks | Most critical, affects everything else |
| M2 Target Management | 1 dev-week | Parser + admin UI |
| M3 Detection & Events | 2 dev-weeks | Algorithm tuning + external vantage agent |
| M4 Dashboard & API | 2 dev-weeks | API first, UI second |
| M5 Hardening & Ops | 1 dev-week | Docs, auth, deploy scripts |
| M6 Review | 1 dev-week | Buffer for findings |
| **Total** | **10 dev-weeks (~2.5 months, 1 dev)** | Parallelising frontend/backend can cut to ~6 weeks |

## 7. Open Questions (Answered / To Close)

1. **Probe node placement**: Will all probes run from a single internal host, or do we need multi-ISP agents (e.g., residential, business, mobile exits) inside the VPN?  
   → *To answer before M1.*
2. **Internet exit strategy**: The monitoring host itself must reach the internet. Will it use a dedicated NAT/VPN exit, or a corporate proxy? This affects Docker networking and DNS configuration.  
   → *To answer before M1.*
3. **Target count / throughput**: Is the scope only the official RKN dump (~80k–200k records) or also custom lists? This impacts DB indexing and probe throughput design.  
   → **Resolved: v1.0 = ~100 curated domains, 10-minute interval.** Scaling to 200k/5-min is architected but not required in v1.0.
4. **SLA / retention**: How long must historical probe results be kept? 30 days? 1 year forever? This drives partitioning strategy.  
   → *Default: 90 days results, 1 year events (configurable). Partitioning designed-in but disabled at this scale.*
5. **Alert noise tolerance**: Should alerts fire on every `suspected` hop, or only confirmed `blocked`? Need tuning parameters and quiet hours?  
   → *Default: `blocked` only; `suspected` logged but no alert.*
6. **Access control**: Who uses the dashboard — internal engineers only, or also external stakeholders? Determines auth method (basic auth vs OAuth2).  
   → *Default: API key + basic auth (internal only).*
7. **External vantage point**: Do we already have an out-of-RU server/VPS to act as a control probe, or is that a future addition?  
   → *Required by M3; if unavailable, delay M3 until provisioned.*

## 8. Suggested Ticket Breakdown (for kanban)

- `INFRA-1` Bootstrap repo, CI, dev Docker Compose
- `CORE-1` HTTP/HTTPS probe engine + storage (with Semaphore for future scaling)
- `CORE-2` DNS probe engine + multi-resolver support
- `CORE-3` APScheduler wiring + jitter + retry
- `CORE-4` DB schema + indexes; partitioning schema designed-in but not required
- `CORE-5` `/health` and `/metrics` (Prometheus) self-monitoring
- `DATA-1` RKN / curated list ingestor (`csv.DictReader` + `asyncpg` batch insert)
- `DATA-2` Target admin (CRUD, tags, pause/resume)
- `ALGO-1` Blockage classifier + scoring logic
- `ALGO-2` Event log (state transitions)
- `ALGO-3` External vantage agent (out-of-RU probe)
- `API-1` FastAPI scaffolding + auth middleware
- `API-2` REST endpoints (targets, results, events)
- `UI-1` Dashboard framework (HTMX + Alpine.js) + target list/search
- `UI-2` Target detail page with timeline + charts
- `OPS-1` Production deployment docs & Docker Compose
- `OPS-2` Backup & restore procedure

## 9. Next Immediate Steps

1. Approve the revised plan (this document).
2. Answer Open Questions #1, #2, #7 (probe placement, internet exit, external vantage VPS).
3. Create kanban children for M0/M1 and assign to developers.
4. Set up a dev VM / container host with internet access for probe testing.
5. *(Optional)* Set up a small proxy/relay if external alerting (Telegram, Slack) is needed alongside the internal `/alerts/outgoing` webhook.

---
*Plan version: 1.0 | Status: APPROVED | Reviewed by default, all blockers resolved, user confirmed 100 domains / 10 min*
