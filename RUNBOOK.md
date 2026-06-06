# RKN Blocks Monitoring — Operations Runbook

## Start (dev)

```bash
docker compose up -d db
uvicorn rknmon.api.main:app --reload --host 0.0.0.0 --port 8000
```

## Start (prod)

```bash
cp .env.example .env
# edit .env
docker compose -f docker-compose.prod.yml up -d
```

## Backup

```bash
DATABASE_URL=postgresql://... ./scripts/backup.sh
# or crontab: 0 3 * * * DATABASE_URL=... /app/scripts/backup.sh
```

## Synthetic data for load test

```bash
DATABASE_URL=... python scripts/generate_synthetic.py 500
locust -f scripts/locustfile.py --host http://127.0.0.1:8000
```

## Auth

All API endpoints (except health, metrics, UI, docs) require `X-API-Key` header.
Default key: `dev-key-change-me`. Set via env `API_KEY`.

## Rate limits

- GET: 100/min
- POST/PATCH/DELETE: 20/min
- Export: 30/min

## Health checks

- `GET /health` — DB connectivity
- `GET /metrics` — Prometheus

## Common issues

1. **DB connection refused** — check `DATABASE_URL` and that PG is running
2. **403 on API calls** — add `X-API-Key` header or check exempt paths
3. **Backup fails** — ensure `pg_dump` is installed and `DATABASE_URL` is set
