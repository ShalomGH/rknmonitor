# RKN Blocks Monitoring — Operations Runbook

## Start (dev)

```bash
docker compose up -d db
uvicorn rknmon.api.main:app --reload --host 0.0.0.0 --port 8000
```

## Start (prod)

```bash
cp .env.example .env
# edit .env — обязательно поменять GRAFANA_ADMIN_PASSWORD и API_KEY
docker compose -f docker-compose.prod.yml up -d
```

### Что поднимается в prod (docker-compose.prod.yml)

| Сервис | Порт | Описание |
|--------|------|----------|
| Postgres | 127.0.0.1:5432 | БД, только локальный доступ |
| rknmon app | 0.0.0.0:8000 | FastAPI + probes + self-metrics |
| Prometheus | — (только внутри сети) | Сбор метрик с `/metrics` rknmon |
| Grafana | 0.0.0.0:3000 | Дашборд с визуализацией (логин/пароль из `.env`) |

### Prometheus и Grafana после старта

```bash
# Проверить что все сервисы подняты
docker compose -f docker-compose.prod.yml ps

# Проверить что Prometheus собирает метрики
docker compose -f docker-compose.prod.yml exec prometheus wget -qO- http://app:8000/metrics | head

# Логин в Grafana: http://<host>:3000
# Логин/пароль = GRAFANA_ADMIN_USER / GRAFANA_ADMIN_PASSWORD из .env
# Дашборд "RKN Blocks Monitoring" подгружается автоматически через provisioning
```

## Бизнес-метрики (custom metrics)

Приложение экспортирует кастомные Prometheus метры на `/metrics`:

- `rknmon_active_targets` — число активных таргетов
- `rknmon_targets_by_state{state}` — таргеты по состоянию (clear/suspected/blocked)
- `rknmon_events_total{event_type}` — счётчик событий
- `rknmon_probe_latest_response_ms{target_id,domain,probe_type}` — последняя latency (http/dns)

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
Grafana имеет собственную аутентификацию (admin panel).

## Rate limits

- GET: 100/min
- POST/PATCH/DELETE: 20/min
- Export: 30/min

## Health checks

- `GET /health` — DB connectivity
- `GET /metrics` — Prometheus
- `docker compose -f docker-compose.prod.yml ps` — состояние контейнеров

## Common issues

1. **DB connection refused** — check `DATABASE_URL` and that PG is running
2. **403 on API calls** — add `X-API-Key` header or check exempt paths
3. **Backup fails** — ensure `pg_dump` is installed and `DATABASE_URL` is set
4. **Grafana не видит Prometheus** — проверить что `prometheus` внутри Docker сети `rknmon` доступен: `docker compose exec grafana ping prometheus`
5. **Дашборд не подгрузился** — проверить `grafana/provisioning/datasources/datasource.yml` и права на `/var/lib/grafana/dashboards`
