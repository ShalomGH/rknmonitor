# RKN Blocks Monitoring v1.0.0

Мониторинг блокировок РКН: проверка доступности доменов через HTTP(S) + DNS, обнаружение подмены/блокировки, алерты и дашборд.

## Быстрый старт (dev)

```bash
docker compose up -d db
uvicorn rknmon.api.main:app --reload --host 0.0.0.0 --port 8000
```

## Быстрый старт (prod)

```bash
cp .env.example .env
# edit .env
docker compose -f docker-compose.prod.yml up -d
```

## Компоненты

- `src/rknmon/api/` — FastAPI (REST: targets, events, probes, alerts, stats, export; UI dashboard; health `/health`; Prometheus `/metrics`)
- `src/rknmon/probes/` — HTTP + DNS пробы, scheduler, classifier, state engine, evaluator
- `src/rknmon/alerts/` — generic webhook alerting (VPN-safe)
- `src/rknmon/ingest/` — загрузка списков целей (csv.DictReader)
- `src/rknmon/models/` — Pydantic схемы
- `templates/` — Jinja2 шаблоны (dashboard, target detail)
- `migrations/` — Alembic stub
- `tests/` — pytest, 19 tests

## REST API эндпоинты

| Path | Method | Auth | Описание |
|------|--------|------|----------|
| `/` | GET | no | App info |
| `/health` | GET | no | Liveness + DB connectivity |
| `/metrics` | GET | no | Prometheus |
| `/ui/dashboard` | GET | no | HTML дашборд |
| `/ui/target/{id}` | GET | no | Страница цели |
| `/ui/dashboard_data` | GET | no | JSON для Chart.js дашборда |
| `/targets` | GET/POST | X-API-Key | Список / создание целей |
| `/targets/{id}` | GET/PATCH/DELETE | X-API-Key | Цель |
| `/events` | GET | X-API-Key | События |
| `/probes/latest` | GET | X-API-Key | Последние пробы |
| `/probes/statistics` | GET | X-API-Key | Статистика проб |
| `/alerts/webhook` | GET | X-API-Key | Статус webhook |
| `/stats` | GET | X-API-Key | Агрегированная статистика |
| `/export/targets` | GET | X-API-Key | Экспорт (json/csv) |
| `/export/events` | GET | X-API-Key | Экспорт событий (json/csv) |

## Авторизация

Все API endpoints (кроме `/health`, `/metrics`, `/ui/*`, `/docs`, `/openapi.json`) требуют заголовок:
```
X-API-Key: your-key
```

Настраивается через env `API_KEY`.

## Rate limiting

- slowapi, по IP
- GET: 100/min, POST/PATCH/DELETE: 20/min, Export: 30/min

## Алгоритм обнаружения блокировки (rule-based)

| Сигнал | Индикатор | Баллы |
|--------|-----------|-------|
| DNS NXDOMAIN | Подозрение | +2 |
| DNS tampering | Подмена IP | +2 |
| HTTP timeout | Таймаут | +2 |
| HTTP 451/403/402 | Блочная страница | +2 |
| External vantage reachable | Подтверждение блока | auto-blocked |

- score >= 4 → `blocked`
- score >= 2 → `suspected`
- иначе → `clear`

## Масштаб v1.0

~100 доменов, интервал 10 мин. Архитектура рассчитана на 200k+ при необходимости (concurrency semaphore, batch INSERT, partitioning designed-in).

## Операции

См. [RUNBOOK.md](RUNBOOK.md) — бэкапы, нагрузочные тесты, troubleshooting.
