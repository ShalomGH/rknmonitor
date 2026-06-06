# RKN Blocks Monitoring

Мониторинг блокировок РКН: проверка доступности доменов через HTTP(S) + DNS, обнаружение подмены/блокировки, алерты и дашборд.

## Быстрый старт (dev)

```bash
cd /home/www/projects/rkn-blocks-monitoring
docker compose up -d db
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python3 -c "import asyncio; from rknmon.db_schema import init_schema; asyncio.run(init_schema())"
PYTHONPATH=src uvicorn rknmon.api.main:app --reload
```

## Структура

- `src/rknmon/api/` — FastAPI (REST, health, metrics)
- `src/rknmon/probes/` — HTTP + DNS пробы
- `src/rknmon/ingest/` — загрузка списков целей
- `src/rknmon/models/` — Pydantic схемы
- `migrations/` — Alembic (подготовлено, пока используется `init_schema`)
- `tests/` — pytest

## Масштаб v1.0

~100 доменов, интервал 10 мин. Архитектура расчитана на 200k+ при необходимости.
