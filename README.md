# RKN Blocks Monitoring

> **LLM-агенты:** сначала прочитать [`AGENTS.md`](AGENTS.md), затем [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) или [`QUICKREF.md`](QUICKREF.md). Этот файл предназначен для людей: обзор проекта, архитектура и запуск central/agent.

`rkn-blocks-monitoring` — система мониторинга сетевых блокировок и доступности Xray-профилей из нескольких точек наблюдения. Central-сервер хранит результаты и экспортирует метрики; Grafana является единственным UI для дашбордов и диагностики. Edge-агенты запускаются на любых Linux-нодах и отправляют проверки в central по outbound HTTPS.

## Что делает проект

- Проверяет HTTP(S) и DNS-доступность доменов.
- Классифицирует состояние целей: `clear`, `suspected`, `blocked`.
- Принимает результаты от удалённых агентов через `/agent/*` API.
- Проверяет DPI-сигналы по набору контрольных URL.
- Проверяет Xray-профили из подписок через локальные SOCKS-inbound'ы sidecar-контейнера.
- Хранит данные в PostgreSQL, отдаёт `/metrics` для Prometheus и Grafana.
- Поддерживает одноразовые invite-токены для установки агента одной командой.

## Архитектура

```text
                 HTTPS, X-Node-API-Key
┌────────────────────────────────────────────────────────────────┐
│ Edge agent: VPS / home server / Raspberry Pi / mini-PC          │
│                                                                │
│  rknmon-agent                                                  │
│  ├─ register / heartbeat                                       │
│  ├─ GET /agent/targets                                         │
│  ├─ HTTP + DNS probes                                          │
│  ├─ DPI probes                                                 │
│  └─ Xray probes via socks5h://127.0.0.1:11001+                 │
│                                                                │
│  rknmon-xray sidecar                                           │
│  └─ waits for /config/xray.generated.json                      │
└───────────────────────────────┬────────────────────────────────┘
                                │ outbound only
                                ▼
┌────────────────────────────────────────────────────────────────┐
│ Central server                                                  │
│                                                                │
│  nginx :8443 ──► rknmon_app :8000 inside Docker                │
│                    host port: 23234                            │
│                  ├─ FastAPI REST API                           │
│                  ├─ scheduler for central probes               │
│                  ├─ /metrics                                   │
│                  └─ /install-agent.sh                          │
│                                                                │
│  rknmon_db          PostgreSQL                                 │
│  rknmon_prometheus  scrapes rknmon_app:8000/metrics            │
│  rknmon_grafana     dashboards provisioned from ./grafana      │
└────────────────────────────────────────────────────────────────┘
```

### Основные инварианты

- Агент не открывает входящие порты. Весь трафик идёт наружу в central API.
- Агент не поднимает TUN/VPN и не меняет default route хоста.
- Xray используется только как локальный SOCKS-proxy внутри Docker network namespace.
- Секреты лежат в `.env`, `.env.agent`, `.env.xray`; эти файлы не коммитятся.
- Public installer не требует git clone и Python на машине агента.
- Встроенного HTML/JS frontend в FastAPI нет: пользовательский интерфейс мониторинга — Grafana.

## Структура репозитория

| Путь | Назначение |
|---|---|
| `src/rknmon/api/` | FastAPI-приложение, admin API, agent API, auth middleware |
| `src/rknmon/agent/` | Код edge-агента: config, client, runner, DPI/Xray probes, CLI |
| `src/rknmon/probes/` | HTTP/DNS probes, scheduler, classifier, evaluator, state engine |
| `src/rknmon/db_schema.py` | Инициализация PostgreSQL-схемы без SQLAlchemy ORM |
| `grafana/` | Provisioning datasources и dashboards |
| `prometheus/` | Prometheus scrape config |
| `monitoring/nginx/` | Nginx reverse proxy config example |
| `deploy/` | Agent installer и agent deploy notes |
| `docker-compose.prod.yml` | Central stack |
| `docker-compose.agent.yml` | Manual/build agent stack |
| `docker-compose.agent.public.yml` | Public/pull-only agent stack |
| `RUNBOOK.md` | Операционный runbook |

## Запуск central-сервера

### Dev

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

cp .env.example .env
# отредактировать .env при необходимости

docker compose up -d db
uvicorn rknmon.api.main:app --reload --host 127.0.0.1 --port 23234
```

Проверка:

```bash
curl -fsS http://127.0.0.1:23234/health
curl -fsS http://127.0.0.1:23234/metrics/ | head
```

### Prod

`docker-compose.prod.yml` использует готовый image `rknmon:1.0.0`, поэтому перед первым запуском его нужно собрать локально или заменить `image:` на опубликованный registry image.

```bash
cp .env.example .env
# обязательно поменять POSTGRES_PASSWORD, API_KEY, GRAFANA_ADMIN_PASSWORD, GRAFANA_ROOT_URL

sudo docker build -t rknmon:1.0.0 .
sudo docker compose -f docker-compose.prod.yml up -d
```

Проверка:

```bash
sudo docker compose -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1:23234/health
sudo docker compose -f docker-compose.prod.yml exec prometheus \
  wget -qO- http://app:8000/metrics | head
```

В production публичный вход должен идти через nginx `:8443` с TLS и IP whitelist. Host port app `:23234`, PostgreSQL, Prometheus и Grafana не должны быть открыты напрямую в интернет; если порт опубликован compose-файлом, его нужно закрывать firewall/IP whitelist.

## Запуск edge-агента

Есть два способа установки.

### Вариант A: public installer через invite-токен

Этот путь предназначен для удалённых нод, где не нужно клонировать репозиторий.

1. На central/admin машине создать invite:

```bash
export RKNMON_CENTRAL_URL=https://monitor.example.com
export RKNMON_ADMIN_API_KEY=<central-api-key>

rknmon-admin agent-invite \
  --name friend-msk \
  --location msk \
  --provider mts \
  --modes dpi
```

Для DPI + Xray:

```bash
rknmon-admin agent-invite \
  --name friend-spb \
  --location spb \
  --provider rostelecom \
  --modes dpi,xray \
  --xray-sub 'https://sub.example/one,https://sub.example/two' \
  --xray-name 'sub-one,sub-two'
```

2. На машине агента выполнить команду, которую напечатал CLI:

```bash
curl -fsSL https://monitor.example.com/install-agent.sh | sudo bash -s -- \
  --central https://monitor.example.com \
  --token <invite-token>
```

Installer выполняет следующие действия:

1. Устанавливает Docker и docker compose plugin, если их нет.
2. Создаёт `/opt/rknmon-agent`.
3. Скачивает `docker-compose.agent.public.yml` с central.
4. Обменивает invite token через `POST /agent/bootstrap` на постоянный `NODE_API_KEY`.
5. Записывает `.env.agent` и `.env.xray` с правами `0600`.
6. Запускает `rknmon-xray` и `rknmon-agent`.
7. Показывает статус и последние логи.

Управление invite-токенами:

```bash
rknmon-admin agent-list-invites
rknmon-admin agent-list-invites-all
rknmon-admin agent-revoke-invite <invite-id>
```

### Вариант B: manual deploy из репозитория

Этот путь удобен для собственной ноды с SSH-доступом и ручным управлением конфигами.

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin git
sudo usermod -aG docker "$USER"
newgrp docker

git clone <repo-url> /opt/rkn-blocks-monitoring
cd /opt/rkn-blocks-monitoring

cp .env.agent.example .env.agent
cp .env.xray.example .env.xray
chmod 600 .env.agent .env.xray

# отредактировать CENTRAL_API_URL, NODE_API_KEY, AGENT_NAME,
# при необходимости XRAY_SUBSCRIPTION_URLS / XRAY_SUBSCRIPTION_NAMES

docker compose -f docker-compose.agent.yml up -d --build
```

One-shot проверка агента:

```bash
docker compose -f docker-compose.agent.yml run --rm rknmon-agent --once
```

Логи:

```bash
docker compose -f docker-compose.agent.yml logs -f rknmon-agent
docker compose -f docker-compose.agent.yml logs -f rknmon-xray
```

## Agent API flow

| Endpoint | Method | Auth | Назначение |
|---|---:|---|---|
| `/agent/bootstrap` | POST | invite token in body | Обмен invite token на постоянный `NODE_API_KEY` |
| `/agent/register` | POST | `X-Node-API-Key` | Регистрация/обновление ноды |
| `/agent/heartbeat` | POST | `X-Node-API-Key` | Keepalive |
| `/agent/targets` | GET | `X-Node-API-Key` | Получить список целей для проверки |
| `/agent/results` | POST | `X-Node-API-Key` | Отправить HTTP/DNS probe results |
| `/agent/dpi-results` | POST | `X-Node-API-Key` | Отправить DPI probe results |
| `/agent/xray-results` | POST | `X-Node-API-Key` | Отправить Xray probe results |

## Admin/API endpoints

| Endpoint | Method | Auth | Назначение |
|---|---:|---|---|
| `/health` | GET | no | Liveness + DB connectivity |
| `/metrics` | GET | no | Prometheus metrics |
| `/targets` | GET/POST | `X-API-Key` | CRUD целей |
| `/targets/{id}` | GET/PATCH/DELETE | `X-API-Key` | Одна цель |
| `/events` | GET | `X-API-Key` | События |
| `/probes/latest` | GET | `X-API-Key` | Последние пробы |
| `/probes/statistics` | GET | `X-API-Key` | Статистика проб |
| `/stats` | GET | `X-API-Key` | Агрегированная статистика |
| `/export/targets` | GET | `X-API-Key` | Экспорт целей |
| `/export/events` | GET | `X-API-Key` | Экспорт событий |
| `/admin/agents/invites` | GET/POST | `X-API-Key` | Управление install invites |

Отдельных `/ui/*` endpoints нет. Просмотр состояния, диагностика блокировок и Xray-профилей выполняются через provisioned Grafana dashboards.

## Авторизация и секреты

Central admin API использует заголовок:

```text
X-API-Key: REDACTED_CENTRAL_API_KEY
```

Agent API использует отдельный заголовок:

```text
X-Node-API-Key: REDACTED_NODE_API_KEY
```

Не сохранять реальные API keys, invite tokens, passwords и Xray subscription URLs в README, issues, chat logs или git history. В документации использовать `<redacted>` / `<...>` placeholders.

## Xray monitoring

Agent и Xray работают двумя контейнерами:

- `rknmon-agent` генерирует `/config/xray.generated.json`, ждёт SOCKS-порты и выполняет probe-запросы.
- `rknmon-xray` ждёт появления `/config/xray.generated.json`, затем запускает `xray run -config /config/xray.generated.json`.

Ключевые переменные:

```bash
XRAY_ENABLED=true
XRAY_SUBSCRIPTION_URLS=https://example.invalid/sub-one,https://example.invalid/sub-two
XRAY_SUBSCRIPTION_NAMES=sub-one,sub-two
XRAY_TEST_URL=https://cp.cloudflare.com/
XRAY_SOCKS_START_PORT=11001
XRAY_CONFIG_PATH=/config/xray.generated.json
XRAY_WAIT_FOR_SOCKS=true
XRAY_READY_TIMEOUT_SECONDS=90
```

`XRAY_SUBSCRIPTION_NAMES` должны идти в том же порядке, что и `XRAY_SUBSCRIPTION_URLS`. Эти имена используются как безопасные labels в Prometheus/Grafana.

## DPI monitoring

DPI checks включаются на агенте через `.env.agent`:

```bash
DPI_ENABLED=true
DPI_TARGETS=YouTube=www.youtube.com,Discord=discord.com,Telegram=api.telegram.org
DPI_WHITELISTED_URLS=https://ya.ru/,https://vk.ru/
DPI_REGULAR_URLS=https://github.com/,https://www.google.com/
DPI_TIMEOUT_SECONDS=10
DPI_L4_PAYLOAD_BYTES=65536
```

## Тесты и проверки

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

Дополнительные проверки:

```bash
ruff check .
python -m compileall src tests
```

## Операции

Подробные команды для backup, troubleshooting, Prometheus/Grafana и agent diagnostics находятся в [`RUNBOOK.md`](RUNBOOK.md).
