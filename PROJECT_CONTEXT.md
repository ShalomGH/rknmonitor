# RKN Blocks Monitoring — Project Context for LLMs

> Документ, который любая новая сессия LLM должна прочитать первой. Даёт полный контекст проекта, его историю, текущее состояние, архитектуру, инварианты, runbook, и соглашения.

---

## 1. Что это за проект

**`rkn-blocks-monitoring`** — сервис мониторинга блокировок РКН и доступности VPN/Xray-профилей.

Два режима работы:

1. **Central server** (на `monitor.example.com`, порт `23234` за nginx `8443`) — FastAPI, PostgreSQL, Prometheus, Grafana. Принимает результаты, хранит, отдаёт `/metrics`, даёт дашборд.
2. **Agent** (на Raspberry Pi дома, ARMv7, доступ через `ssh rpi` → reverse SSH tunnel к Hermes) — периодически проверяет HTTP/DNS-цели, плюс Xray-профили, отправляет результаты в central.

Назначение: узнавать, что блокирует РКН, как работает DPI, и какие Xray-профили реально живые.

---

## 2. Где что лежит

```text
/home/www/projects/rkn-blocks-monitoring/   # репозиторий (central + agent код)
├── src/rknmon/
│   ├── api/                # FastAPI: main, agents, auth, targets, events, probes, stats, export, alerts
│   ├── agent/              # xray.py, runner.py, cli.py, client.py, config.py
│   ├── probes/             # http_probe, dns_probe, orchestrator, scheduler, evaluator, classifier, state_engine, cleanup
│   ├── alerts/webhook.py   # generic webhook alerts
│   ├── ingest/csv_loader.py
│   ├── models/schemas.py   # Pydantic, в т.ч. XrayProbeIn / XrayProbeBatchIn
│   ├── config/settings.py  # Pydantic-settings
│   ├── custom_metrics.py   # Prometheus gauges/counters (в т.ч. rknmon_xray_profile_*)
│   ├── db.py / db_schema.py
│   └── ui/                 # Jinja2 dashboard
├── static/                 # chart.umd.min.js (vendored Chart.js)
├── templates/              # Jinja2 (dashboard.html, target_detail.html)
├── scripts/                # backup.sh, evaluate.py, generate_synthetic.py, ingest.py, locustfile.py
├── grafana/
│   ├── provisioning/datasources/datasource.yml
│   ├── provisioning/dashboards/dashboards.yml   # editable: true, allowUiUpdates: true
│   └── dashboards/
│       ├── rknmon.json                          # main dashboard (uid rknmon-main)
│       └── xray.json                             # Xray profiles (uid rknmon-xray)
├── prometheus/prometheus.yml
├── monitoring/nginx/nginx.conf                   # SSL proxy 8443 → 23234
├── docker-compose.prod.yml                       # central stack
├── docker-compose.agent.yml                      # RPi agent stack (rknmon-agent + rknmon-xray sidecar)
├── Dockerfile / Dockerfile.agent
├── deploy/README-agent.md                        # deploy guide для RPi
├── docs/superpowers/plans/2026-06-09-xray-monitoring.md
├── tests/                                        # 59 тестов, pytest
├── AGENTS.md                                     # точка входа для LLM-агентов
├── QUICKREF.md                                   # TL;DR карточка
├── PROJECT_CONTEXT.md                            # полный LLM-контекст (этот файл)
├── PROJECT_MANIFEST.md                           # LLM-readable manifest
├── RUNBOOK.md                                    # ops runbook
├── IMPLEMENTATION_PLAN.md                        # история M0-M6
└── README.md                                     # human quick start
```

На малине (`ssh rpi`):

```text
/home/ubuntu/rkn-blocks-monitoring-agent/   # копия репо
└── .env.xray                               # XRAY_SUBSCRIPTION_URLS + XRAY_SUBSCRIPTION_NAMES (приватные)
```

---

## 3. Архитектура

```text
┌───────────────────────────────────────────────────────┐
│ Central (monitor.example.com)                               │
│  nginx 8443 → 23234                                   │
│  rknmon_app :23234  (FastAPI, /metrics, /agent/*)     │
│  rknmon_db   :5432   (Postgres, 127.0.0.1)            │
│  rknmon_prometheus (scrape rknmon_app:23234/metrics)  │
│  rknmon_grafana :3000                                 │
└───────────────────────────▲───────────────────────────┘
                            │ HTTPS out, X-Node-API-Key
                            │
┌───────────────────────────┴───────────────────────────┐
│ RPi Home (ARMv7)                                      │
│  rknmon-agent (network_mode: service:rknmon-xray)      │
│     ├─ registers/heartbeats at central                │
│     ├─ fetches /agent/targets                         │
│     ├─ HTTP+DNS probes                                │
│     └─ Xray: download subscription, write config,     │
│        curl --proxy socks5h://127.0.0.1:<port>        │
│        POST /agent/xray-results                       │
│  rknmon-xray (teddysun/xray:latest, armv7)            │
│     └─ waits for /config/xray.generated.json          │
└───────────────────────────────────────────────────────┘
```

Ключевые инварианты архитектуры:

1. **Agent outbound-only** — никаких входящих портов, никакого VPN на хосте. Всё ходит наружу через HTTPS к central.
2. **No TUN / no iptables** — Xray поднимается в sidecar, SOCKS-инбаунды слушают `127.0.0.1`, default route не меняется. Только `curl --proxy socks5h://127.0.0.1:<port>` идёт через Xray.
3. **Shared network namespace** — agent и Xray через `network_mode: service:rknmon-xray` делят loopback, агент видит Xray SOCKS как `127.0.0.1:11001+`.
4. **One SOCKS inbound per profile** — для каждого профиля подписки свой SOCKS-порт и outbound; routing rule связывает их.
5. **Xray config flow:**
   - agent скачивает подписки → генерирует `/config/xray.generated.json`
   - Xray sidecar `until [ -s /config/xray.generated.json ]; do sleep 1; done` → `exec xray run -config /config/xray.generated.json`
   - agent ждёт TCP-порты SOCKS → запускает probes
6. **Schema managed in `db_schema.py`** — additive `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`; init через `pg_try_advisory_lock(1)`, чтобы не было race при 2+ uvicorn workers.
7. **Raw asyncpg, не SQLAlchemy** — performance, batch INSERT.
8. **Custom Prometheus metrics:**
   - `rknmon_active_targets`
   - `rknmon_targets_by_state{state}`
   - `rknmon_events_total{event_type}`
   - `rknmon_probe_latest_response_ms{...}`
   - `rknmon_xray_profile_status{agent, subscription, profile, protocol, transport, server}` (0/1)
   - `rknmon_xray_profile_latency_ms{agent, subscription, profile, protocol, transport, server}`
   - `rknmon_xray_profile_errors_total{agent, subscription, profile, protocol, transport, server, error_type}`

---

## 4. Ключевые API

| Path | Method | Auth | Что |
|------|--------|------|------|
| `/` | GET | no | app info |
| `/health` | GET | no | liveness + DB |
| `/metrics` | GET | no | Prometheus |
| `/ui/dashboard` | GET | no | HTML Chart.js |
| `/agent/register` | POST | X-Node-API-Key | регистрация ноды |
| `/agent/heartbeat` | POST | X-Node-API-Key | keepalive |
| `/agent/targets` | GET | X-Node-API-Key | получить цели |
| `/agent/results` | POST | X-Node-API-Key | HTTP/DNS результаты |
| `/agent/xray-results` | POST | X-Node-API-Key | Xray probe-результаты |
| `/targets`, `/events`, `/probes/*`, `/stats`, `/export/*`, `/alerts/webhook` | * | X-API-Key | admin API |

Auth:

- central API endpoints — `X-API-Key` (env `API_KEY`)
- agent endpoints — `X-Node-API-Key` (per-node ключ из `probe_nodes.api_key`)

---

## 5. Env vars

### Central (`.env`, не в git)

```bash
POSTGRES_USER=rknmon
POSTGRES_PASSWORD=<32+ hex>
POSTGRES_DB=rknmon
DATABASE_URL=postgresql://rknmon:***@db:5432/rknmon
API_KEY=<32+ hex>
LOG_LEVEL=info
PROBE_INTERVAL_MINUTES=10
PROBE_CONCURRENCY=10
PROBE_JITTER_SECONDS=3
EVENT_RETENTION_DAYS=365
RESULT_RETENTION_DAYS=90
PROXY_URL=                # опционально corporate proxy
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=<secret>
```

### Agent (`.env.agent`)

```bash
CENTRAL_API_URL=https://monitor.example.com:8443
NODE_API_KEY=<per-node>
AGENT_NAME=rknmon-agent-rpi-home
AGENT_LOCATION=home
AGENT_PROVIDER=domru
AGENT_VERSION=0.1.0
PROBE_INTERVAL_SECONDS=300
PROBE_CONCURRENCY=20
XRAY_ENABLED=false
LOG_LEVEL=INFO
```

### Xray (`.env.xray`)

```bash
XRAY_ENABLED=true
XRAY_SUBSCRIPTION_URLS=https://sub1.example/xxx,https://sub2.example/yyy
XRAY_SUBSCRIPTION_NAMES=rpi-main,rpi-secondary     # safe labels для Grafana
XRAY_TEST_URL=https://cp.cloudflare.com/
XRAY_SOCKS_START_PORT=11001
XRAY_CONFIG_PATH=/config/xray.generated.json
XRAY_WAIT_FOR_SOCKS=true
XRAY_READY_TIMEOUT_SECONDS=90
```

`XRAY_SUBSCRIPTION_URLS` и `XRAY_SUBSCRIPTION_NAMES` — в **одном порядке**, через запятую. Имена показываются в Grafana как filter `Subscription` и как Prometheus label `subscription="..."`.

---

## 6. Текущее состояние (по состоянию на 2026-06-09)

### Что работает в проде (central)

- Postgres + app + Prometheus + Grafana + nginx, всё в Docker.
- Endpoint `/agent/xray-results` принимает данные, метрики экспортируются.
- Grafana дашборды:
  - `rknmon-main` — основной мониторинг (uid `rknmon-main`)
  - `rknmon-xray` — Xray профили (uid `rknmon-xray`), 12 панелей, фильтры `Agent` + `Subscription`.
- Provisioning включён с `editable: true, allowUiUpdates: true` — дашборды можно править из UI.

### Что работает на малине

- Контейнеры `rknmon-agent` + `rknmon-xray` (`teddysun/xray:latest`, ARMv7).
- Сейчас 2 примерные подписки: `rpi-main`, `rpi-secondary`. Количество профилей и статусы зависят от локальной `.env.xray`.
- SOCKS-порты: `11001..11012` на `127.0.0.1`.
- Проба идёт через `curl --proxy socks5h://127.0.0.1:<port> https://cp.cloudflare.com/`.

### Тесты

- `pytest -q` → **59 passed** в `tests/`.
- Ключевые:
  - `test_xray_subscription.py` — парсер base64 / vless/vmess/trojan/ss
  - `test_xray_agent_runner.py` — runner flow с mock fetch и probe
  - `test_xray_agents_api.py` — ingest endpoint
  - `test_xray_docker_flow.py` — compose skeleton
  - `test_agents_api.py` — agent registration/heartbeat/targets/results
  - `test_evaluator_fix.py`, `test_scheduler_graceful.py` и т.п.

---

## 7. История (что уже сделано, в хронологическом порядке)

| Дата | Что |
|------|-----|
| M0 | bootstrap repo, probes, DB, API, scheduler, self-monitoring |
| M1-M2 | classifier, state engine, evaluator, alerting, probes/alerts API, CLI scripts, 14 тестов |
| M3 | vendored Chart.js (air-gapped), graceful shutdown, retention cleanup, evaluator N+1 fix, advisory lock |
| v1.0.0 | M4-M6: dashboard, auth, rate limits, export, runbook |
| позже | Grafana + Prometheus добавлены в stack; PROJECT_MANIFEST.md для LLM |
| 2026-06-09 | **Xray monitoring** — план в `docs/superpowers/plans/2026-06-09-xray-monitoring.md`, реализация полностью завершена и задеплоена на RPi |
| 2026-06-09 | RPi agent + Xray sidecar запущены, endpoint `/agent/xray-results` принимает данные |
| 2026-06-09 | Grafana dashboard `rknmon-xray` (12 панелей) с фильтрами `Agent` + `Subscription` |
| 2026-06-09 | DB migration: `xray_probe_results.subscription_name` column + index |
| 2026-06-09 | Provisioning dashboards editable + allowUiUpdates = true |

---

## 8. Runbook (короткий)

### Central — управление

```bash
cd /home/www/projects/rkn-blocks-monitoring
sudo docker compose -f docker-compose.prod.yml ps
sudo docker compose -f docker-compose.prod.yml up -d --build
sudo docker compose -f docker-compose.prod.yml restart app
sudo docker compose -f docker-compose.prod.yml logs -f app
sudo docker compose -f docker-compose.prod.yml logs -f grafana
```

Пересобрать image:

```bash
sudo docker build -t rknmon:1.0.0 .
```

### Agent (RPi) — управление

```bash
ssh rpi
cd ~/rkn-blocks-monitoring-agent
docker compose -f docker-compose.agent.yml ps
docker compose -f docker-compose.agent.yml logs -f rknmon-agent
docker compose -f docker-compose.agent.yml logs -f rknmon-xray
docker compose -f docker-compose.agent.yml restart rknmon-agent
```

Обновить код на малине:

```bash
rsync -az --delete --exclude .git --exclude .venv --exclude .pytest_cache \
  --exclude __pycache__ --exclude htmlcov --exclude .coverage \
  --exclude .env --exclude .env.agent --exclude .env.xray \
  ./ rpi:~/rkn-blocks-monitoring-agent/

ssh rpi "cd ~/rkn-blocks-monitoring-agent && \
  docker compose -f docker-compose.agent.yml build rknmon-agent && \
  docker compose -f docker-compose.agent.yml up -d --force-recreate rknmon-agent"
```

### ARMv7 image pitfall

Docker Hub на малине часто зависает. Workaround:

```bash
sudo docker pull --platform linux/arm/v7 IMAGE:TAG
sudo docker save IMAGE:TAG | gzip -1 > /tmp/img.tar.gz
scp /tmp/img.tar.gz rpi:/tmp/img.tar.gz
ssh rpi 'docker load -i /tmp/img.tar.gz'
```

### Запуск тестов

```bash
source .venv/bin/activate
pytest -q
pytest tests/test_xray_agent_runner.py -v
```

### Диагностика

- central: `curl http://127.0.0.1:23234/health` и `curl http://127.0.0.1:23234/metrics/ | head`
- БД: `sudo docker exec rknmon_db psql -U rknmon -d rknmon -P pager=off -c "..."`
- Grafana: проверить datasource `PBFA97CFB590B2093` (uid Prometheus), Postgres `grafana-postgres`
- SOCKS на малине: `ssh rpi 'docker exec rknmon-agent sh -lc "for p in 11001 11002; do curl -sS -o /dev/null -w %{http_code} --max-time 15 --proxy socks5h://127.0.0.1:\${p} https://cp.cloudflare.com/; done"'`

### Grafana: datasource UID

- Prometheus datasource uid = `PBFA97CFB590B2093` (дефолт в provisioning)
- Postgres datasource uid = `grafana-postgres`

### ВАЖНО: секреты

- `.env`, `.env.agent`, `.env.xray` — **не в git**, в `.gitignore`.
- API keys / passwords / tokens **никогда не пишем в README, в чат, в commit**.
- Если всплывают в логах/выводах — заменять на `<redacted>`.

---

## 9. Что осталось / TODO

- Реальные subscription-ссылки на малине пока статичные; в будущем можно добавить ротацию через env-шаблон или vault.
- External vantage point для cross-check блокировок (отдельная VPS за границей) — пока не реализован.
- Multi-vantage agents на других провайдерах (в планах).
- Алёрты на Xray profile failures (transport degraded, error spike) — пока только дашборд.
- Webhook alerts в Telegram — есть generic webhook, но не подключен.

---

## 10. Соглашения (краткая выжимка)

Полный «Не делай» и security pitfalls — в `QUICKREF.md` и `AGENTS.md`. Здесь — только самое важное:

- **TDD:** красный тест → реализация → зелёный тест → рефактор. `pytest -q` зелёный перед коммитом/деплоем.
- **Деплой:** сначала central (`docker build` + `up -d`), потом RPi (`rsync` + `compose up -d`).
- **Секреты:** API keys, tokens, subscription links, passwords — никогда в чат, README, коммиты, память; заменять на `<redacted>`.
- **Метрики проверять ДО "готово":** `curl /metrics` или `psql` для БД.
- **Python 3.12**, `from __future__ import annotations`, Pydantic v2 + pydantic-settings, raw asyncpg (не ORM).
- **Тесты:** pytest, pytest-asyncio, mock через `unittest.mock.AsyncMock`/`patch`.
- **ASCII-only** в коде/Python комментариях и YAML — cyrillic ломает парсинг.
- **Central:** prod через `docker-compose.prod.yml` + nginx. **Agent:** Docker на RPi, не systemd.
- **Bind `0.0.0.0`** только на nginx `:8443`; всё остальное internal/127.0.0.1.
- **iptables whitelist** для всех публичных портов (см. skill `secure-server-run`).

---

## 11. Связанные skills

- `devops/censorship-monitoring` — Xray sidecar pattern, общая архитектура
- `devops/rpi-home-access` — SSH к малине, ARMv7 image workaround
- `devops/secure-server-run` — iptables, security hardening
- `devops/monitoring-stack-docker` — Prometheus + Grafana deploy
- `devops/hermes-dashboard-themes` — Grafana theming
- `superpowers:subagent-driven-development` — multi-agent реализация фич
- `superpowers:executing-plans` — выполнение планов из `docs/superpowers/plans/`
