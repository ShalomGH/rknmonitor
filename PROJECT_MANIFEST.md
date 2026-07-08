# RKN Blocks Monitoring — Project Manifest

> Документ в формате, оптимизированном для LLM-интерпретаторов. Содержит структуру, предположения и рабочие инструкции.

---

## Что это

FastAPI-сервис для мониторинга **DNS и HTTP блокировок** РКН. Периодически (каждые N минут) проверяет список доменов на доступность из вашей сети, записывает результаты и детектирует смену состояния (`clear` → `blocked`, `clear` → `suspected`, обратно).

### Типы детектируемых блокировок

| Тип | Проба | Как детектируется |
|-----|-------|-------------------|
| DNS NXDOMAIN | `dns_probe` | Разрешение домена возвращает NXDOMAIN (провайдер подменяет ответ) |
| DNS tampering | `dns_probe` | Ответ содержит IP заглушки, отличающееся от эталонного |
| TCP/DPI блок | `http_probe` | Connection error / timeout — DPI сбрасывает соединение |
| HTTP-блочная страница | `http_probe` | Статус 451, 403, 402 — провайдер или РКН показывают страницу-заглушку |

**Чего НЕ детектирует:** нет external vantage point (собственного сервера за границей для подтверждения блока). Алертит только на основании сигналов из вашей сети.

---

## Архитектура

### Стек
- **Backend:** FastAPI + asyncpg + SQLAlchemy (raw asyncpg, не ORM)
- **Scheduler:** APScheduler (asyncio executor), jitter + concurrency semaphore
- **HTTP client:** aiohttp (proxy через `PROXY_URL` поддерживается)
- **DNS:** aiodns + системный resolver
- **DB:** PostgreSQL 15, schema init через `db_schema.py` с advisory lock (race condition при 2+ uvicorn workers)
- **Frontend:** Jinja2 шаблоны + Chart.js (вендоризирован, не CDN)
- **Containerization:** Docker, docker compose V2
- **Auth:** `X-API-Key` header для всех эндпоинтов кроме `/health`, `/metrics`, `/ui/*`, `/docs`
- **Rate limiting:** slowapi (GET 100/min, POST 20/min, Export 30/min)

### Модули

```
src/rknmon/
├── api/              # FastAPI routers + main.py (lifespan)
│   ├── main.py       # App factory, lifespan, static/template mounts
│   ├── targets.py    # CRUD для доменов (POST /targets, etc.)
│   ├── events.py     # Журнал событий
│   ├── probes.py     # Результаты проб и статистика
│   ├── stats.py      # Агрегаты
│   ├── export.py     # CSV/JSON экспорт
│   ├── alerts.py     # Webhook alerting
│   ├── agents.py     # Agent API: /agent/register, /agent/heartbeat, /agent/targets, /agent/results, /agent/xray-results (X-Node-API-Key)
│   └── auth.py       # API key middleware
├── agent/            # Код edge-агента, запускается и на central в тестах
│   ├── client.py     # AgentClient: register/heartbeat/fetch_targets/submit_results/submit_xray_results
│   ├── config.py     # Pydantic-settings: central_api_url, node_api_key, xray_subscription_urls, xray_subscription_names, ...
│   ├── xray.py       # XrayProfile, parse_subscription_text, build_xray_config, load_profiles_from_urls
│   ├── runner.py     # run_probe_cycle, run_xray_probe_cycle, write_xray_config, wait_for_tcp_ports, default_probe_xray_profile
│   └── cli.py        # argparse entrypoint: --once, --xray-only, --write-xray-config
├── probes/           # Ядро мониторинга
│   ├── orchestrator.py   # Конкурентный запуск проб с семафором
│   ├── http_probe.py     # HTTP(S) пробы через aiohttp
│   ├── dns_probe.py      # DNS пробы через aiodns
│   ├── evaluator.py      # Batch-анализ результатов (N+1 фикс: 3 batch запроса вместо 2N коррелированных)
│   ├── classifier.py     # Скоринг: clear/suspected/blocked (score-based)
│   ├── state_engine.py   # Фиксация смены состояния, генерация events
│   ├── scheduler.py      # APScheduler wiring, graceful shutdown (отмена активной пробы)
│   └── cleanup.py        # Retention cleanup для probes/events (CronTrigger day='*', hour=3)
├── ingest/           # Загрузка списка доменов (CSV)
│   └── csv_loader.py
├── models/           # Pydantic schemas
│   └── schemas.py    # Target, ProbeResult, Event
├── config/           # Settings
│   └── settings.py   # Pydantic-settings, .env
├── db.py             # Asyncpg pool helper
├── db_schema.py      # DDL + advisory lock
└── alerts/
    └── webhook.py    # Generic webhook alerts (VPN-safe, no external SaaS deps)

templates/            # Jinja2 (dashboard.html, target_detail.html)
static/               # chart.umd.min.js (vendored Chart.js 4.4.3)
scripts/              # Утилиты: backup.sh, evaluate.py, generate_synthetic.py, ingest.py, locustfile.py
```

### State machine

```
clear ──(score >=2)──► suspected ──(score >=4)──► blocked
  ▲                      │                          │
  └──────────────────────┴──────────────────────────┘
         (score < threshold)
```

События (`events` таблица): `state_changed`, `target_blocked`, `target_unblocked`, `probe_failed`.

---

## Пути сетевого доступа

| Путь | Auth | Описание |
|------|------|----------|
| `GET /` | нет | `{"app":"rknmon","version":"1.0.0"}` |
| `GET /health` | нет | Liveness + DB connectivity |
| `GET /metrics` | нет | Prometheus формат |
| `GET /ui/dashboard` | нет | HTML дашборд (Chart.js) |
| `GET /ui/target/{id}` | нет | Деталь по конкретному домену |
| `GET /ui/dashboard_data` | нет | JSON для графиков |
| API CRUD | `X-API-Key` | `/targets`, `/events`, `/probes/*`, `/stats`, `/export/*`, `/alerts/webhook` |

### Безопасность сети (prod)
- **Приложение** (`:23234`, на хосте): bind `0.0.0.0`, iptables whitelist через `DOCKER-USER` цепочку, наружу — через `nginx 8443` (TLS).
- **База данных** (`:5432`): bind `127.0.0.1`, наружу не выставлена.
- **Whitelist IP:** см. `secure-server-run` skill (7 публичных IP + localhost + private subnets). Все остальные → DROP.

---

## Окружение

### Env vars
```bash
POSTGRES_USER=rknmon
POSTGRES_PASSWORD=<генерировать, 32+ hex>
POSTGRES_DB=rknmon
DATABASE_URL=postgresql://rknmon:<pass>@db:5432/rknmon
API_KEY=<генерировать, 32+ hex>
LOG_LEVEL=info
PROBE_INTERVAL_MINUTES=10
PROBE_CONCURRENCY=10          # semaphore для параллельных проб
PROBE_JITTER_SECONDS=3        # jitter перед стартом batch
EVENT_RETENTION_DAYS=365
RESULT_RETENTION_DAYS=90
PROXY_URL=                    # опционально, corporate proxy для HTTP проб
```

### Билд и запуск
```bash
# 1. Зависимости
pip install -e .              # pyproject.toml

# 2. Билд образа
docker build -t rknmon:1.0.0 .

# 3. Запуск
# DB → приложение. Приложение стартует после healthcheck DB.
docker compose -f docker-compose.prod.yml up -d

# 4. Проверка
curl http://127.0.0.1:23234/health
```

### Dev (без Docker)
```bash
docker compose up -d db       # только PostgreSQL
uvicorn rknmon.api.main:app --reload --host 127.0.0.1 --port 23234
# PYTHONPATH=src обязателен (установлен в pyproject.toml при pip install -e .)
```

---

## Тесты
```bash
pytest tests/                 # 59 тестов (актуально на 2026-06-09)
```

Ключевые покрытия: API CRUD, classifier scoring, DNS/HTTP probe mocking, scheduler graceful shutdown, evaluator batch N+1 fix, vendor JS self-hosting.

---

## Ключевые инварианты и архитектурные решения

1. **Raw asyncpg, не SQLAlchemy ORM** — производительность, batch INSERT, прямой доступ к PostgreSQL фичам.
2. **Pooling:** singleton connection pool в `db.py`, создаётся/закрывается в lifespan.
3. **Graceful shutdown:** активная проба (asyncio.Task) отменяется с `await` до 60 сек. Перезапуск — через `run_all`.
4. **Schema init с advisory lock:** `pg_try_advisory_lock(1)` предотвращает race при одновременном `CREATE INDEX IF NOT EXISTS` из 2+ uvicorn workers.
5. **Evaluator N+1 fix:** вместо 2 коррелированных подзапросов на каждый target — 3 batch-запроса: `SELECT * FROM targets`, затем `DISTINCT ON (target_id)` для http и dns с `target_id = any($1)`.
6. **Retention cleanup:** CronTrigger каждый день в 03:00, удаляет старые probes/events по `RESULT_RETENTION_DAYS` / `EVENT_RETENTION_DAYS`.
7. **Vendor JS:** Chart.js vendored в `static/chart.umd.min.js` (CDN не используется — air-gapped/VPN deployment). `test_vendor_js.py` проверяет наличие файла.
8. **No external alert SaaS:** webhook alerts — generic POST, никаких обязательных Telegram/Slack/PagerDuty.

---

## Текущее состояние (после развёртывания)

- ✅ Docker-контейнеры работают, whitelist iptables настроен
- ✅ Вендоризирован Chart.js (CDN отключён)
- ✅ Graceful shutdown + cleanup реализованы
- ✅ Evaluator N+1 fixed (batch queries)
- ✅ Advisory lock для schema init (race condition при старте)
- ✅ **Xray monitoring** — agent+Xray sidecar запущен, `/agent/xray-results` принимает результаты, Grafana `rknmon-xray` (uid) с фильтрами `Agent`/`Subscription` готов
- ✅ **Multi-subscription support** — `XRAY_SUBSCRIPTION_URLS` + `XRAY_SUBSCRIPTION_NAMES` (comma-separated, в одном порядке), примерные safe labels: `edge-main`, `edge-secondary`; реальные URL/статусы живут только в локальной `.env.xray`.
- ✅ **Grafana provisioning editable + allowUiUpdates** — дашборды можно править из UI
- ⚠️ **Списка реальных доменов нет** — в базе только `example.com` (тестовый)
- ⚠️ **External vantage point не реализован** — нет подтверждения блокировки из-за рубежа

### Что нужно сделать дальше

1. **Загрузить список доменов** для мониторинга через `POST /targets` (curl/API) либо `scripts/ingest.py` (CSV).
2. **Настроить webhook alerts** — URL и формат см. `src/rknmon/alerts/webhook.py`.
3. **Добавить external vantage** (опционально) — REST endpoint на сервере за пределами РФ для double-check.
4. **Алёрты на Xray failures** — `rknmon_xray_profile_status{...}==0` или spike в `rknmon_xray_profile_errors_total` (пока только дашборд).
5. **Multi-vantage agents** — добавить edge-агенты на других провайдерах / локациях для cross-ISP корреляции.
6. **TLS / reverse proxy** — в prod nginx уже работает на `:8443` → app `:23234`. Let's Encrypt не подключали — используется существующий сертификат.

---

## Связанные документы

- `README.md` — быстрый старт и endpoints (человеко-ориентированный)
- `AGENTS.md` — точка входа для LLM-агентов, указывает на PROJECT_CONTEXT/QUICKREF
- `PROJECT_CONTEXT.md` — полный LLM-контекст (архитектура, история, инварианты, runbook, соглашения)
- `QUICKREF.md` — TL;DR карточка для новых LLM-сессий
- `RUNBOOK.md` — бэкапы, нагрузочные тесты, troubleshooting
- `deploy/README-agent.md` — deploy guide для edge-агента
- `IMPLEMENTATION_PLAN.md` — история реализации (M1-M6)
- `docs/superpowers/plans/2026-06-09-xray-monitoring.md` — план реализации Xray-фичи
- `.env` — не в git, генерируется руками
