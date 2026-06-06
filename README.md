# RKN Blocks Monitoring

Мониторинг блокировок РКН: проверка доступности доменов через HTTP(S) + DNS, обнаружение подмены/блокировки, алерты и дашборд.

## Быстрый старт (dev)

```bash
cd /home/www/projects/rkn-blocks-monitoring
docker compose up -d db
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
DATABASE_URL=postgresql://rknmon:rknmon_dev@localhost:5432/rknmon uvicorn rknmon.api.main:app --reload
```

## Компоненты

- `src/rknmon/api/` — FastAPI (REST: targets, events, probes, alerts; health `/health`; Prometheus `/metrics`)
- `src/rknmon/probes/` — HTTP + DNS пробы, scheduler, classifier, state engine, evaluator
- `src/rknmon/alerts/` — generic webhook alerting (VPN-safe, без интернет-выхода)
- `src/rknmon/ingest/` — загрузка списков целей (csv.DictReader, без pandas)
- `src/rknmon/models/` — Pydantic схемы
- `migrations/` — Alembic stub (пока `init_schema`)
- `tests/` — pytest, 14 tests

## REST API эндпоинты

| Path | Method | Описание |
|------|--------|----------|
| `/` | GET | App info |
| `/health` | GET | Liveness + DB connectivity |
| `/metrics` | GET | Prometheus |
| `/targets` | GET/POST | Список / создание целей |
| `/targets/{id}` | GET/PATCH/DELETE | Цель |
| `/events` | GET | События (state transitions) |
| `/probes/latest` | GET | Последние пробы |
| `/probes/statistics` | GET | Статистика проб |
| `/alerts/webhook` | GET | Статус конфига webhook |

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
