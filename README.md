# RKN Blocks Monitoring v1.0.0

> **LLM-агенты:** начни с `AGENTS.md` → `PROJECT_CONTEXT.md` (полный контекст для LLM) или `QUICKREF.md` (TL;DR). Этот файл — для быстрого старта человеком.

Мониторинг блокировок РКН: проверка доступности доменов через HTTP(S) + DNS, обнаружение подмены/блокировки, алерты и дашборд.

## Быстрый старт (dev)

```bash
docker compose up -d db
uvicorn rknmon.api.main:app --reload --host 0.0.0.0 --port 23234
```

## Быстрый старт (prod)

```bash
cp .env.example .env
# edit .env
docker compose -f docker-compose.prod.yml up -d
```

## Docker agent (Raspberry / другие ноды)

Агент работает без VPN и без входящих портов: только outbound HTTPS в центральный API.

### Raspberry Pi quick deploy

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin git
sudo usermod -aG docker $USER
newgrp docker

git clone <repo-url> /opt/rkn-blocks-monitoring
cd /opt/rkn-blocks-monitoring
cp .env.agent.example .env.agent
vim .env.agent

docker compose -f docker-compose.agent.yml up -d --build
```

Поток запросов:
- `POST /agent/register`
- `POST /agent/heartbeat`
- `GET /agent/targets`
- `POST /agent/results`
- `POST /agent/xray-results` — если включён `XRAY_ENABLED=true`

### Xray subscription monitoring

`docker-compose.agent.yml` запускает два контейнера:

- `rknmon-agent` — скачивает подписки, пишет `/config/xray.generated.json`, ждёт SOCKS-порты, отправляет результаты в центр.
- `rknmon-xray` — sidecar с `teddysun/xray`, ждёт появления `/config/xray.generated.json` и стартует с ним.

Оба контейнера используют общий network namespace через `network_mode: service:rknmon-xray`, поэтому агент ходит в Xray по `127.0.0.1:11001+`. Системный default route не меняется, TUN/VPN не поднимается, через Xray идут только явные `curl --proxy socks5h://127.0.0.1:<port>` пробы.

Минимальные Xray env:

```bash
XRAY_ENABLED=true
XRAY_SUBSCRIPTION_URLS=https://sub.example/sub-token,https://198.51.100.10/sub-token
XRAY_TEST_URL=https://cp.cloudflare.com/
XRAY_SOCKS_START_PORT=11001
XRAY_CONFIG_PATH=/config/xray.generated.json
XRAY_WAIT_FOR_SOCKS=true
XRAY_READY_TIMEOUT_SECONDS=90
```

One-shot проверка:

```bash
docker compose -f docker-compose.agent.yml run --rm rknmon-agent --once
```

Логи:

```bash
docker compose -f docker-compose.agent.yml logs -f rknmon-agent
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
