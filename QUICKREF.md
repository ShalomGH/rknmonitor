# RKN Blocks Monitoring — Quick Reference Card

> TL;DR для новой сессии LLM. Перед серьёзной работой читай `PROJECT_CONTEXT.md`.

## Что это

Центральный FastAPI-сервис мониторинга РКН-блокировок + Xray-профилей с агентов. Repo: локальная рабочая копия проекта.

## Ключевое в одном абзаце

Agent (любой Linux host/container: VPS, home server, Raspberry Pi, ARM/x86) outbound-only HTTPS → central (`monitor.example.com:8443` → nginx → app `:8000` внутри Docker; host app check `127.0.0.1:23234`). Xray поднимается в sidecar-контейнере `rknmon-xray`, SOCKS-inbound'ы на `127.0.0.1:11001+`. Agent пишет `/config/xray.generated.json`, Xray его ждёт через shell-loop, agent ждёт SOCKS-порты и шлёт пробы через `curl --proxy socks5h://127.0.0.1:<port> <test>`. Результаты → `POST /agent/xray-results`. Хранится в Postgres, экспортируется в Prometheus `rknmon_xray_profile_*`, визуализируется в Grafana dashboard `rknmon-xray` (uid). Подписки на agent host в `.env.xray` как `XRAY_SUBSCRIPTION_URLS` + `XRAY_SUBSCRIPTION_NAMES` (safe labels в том же порядке).

## Где что

| Что | Где |
|-----|-----|
| Repo central+agent code | `/home/www/projects/rkn-blocks-monitoring/` |
| Repo copy на agent host (legacy) | например `/opt/rkn-blocks-monitoring` или `~/rkn-blocks-monitoring-agent/` |
| Подписки агента | локальный `.env.xray` на agent host (`/opt/rknmon-agent/.env.xray` для public installer) |
| Endpoint приёма Xray | `POST /agent/xray-results` (auth `X-Node-API-Key`) |
| Xray dashboard | Grafana → `rknmon-xray` → 12 панелей, фильтры Agent + Subscription |
| Main dashboard | Grafana → `rknmon-main` |
| Prometheus datasource uid | `PBFA97CFB590B2093` |
| Postgres datasource uid | `grafana-postgres` |

## Команды на одной строке

```bash
# central rebuild
sudo docker build -t rknmon:1.0.0 . && \
  sudo docker compose -f docker-compose.prod.yml up -d --force-recreate app grafana

# tests
source .venv/bin/activate && pytest -q

# sync code to a manually managed agent host and rebuild
rsync -az --delete --exclude .git --exclude .venv --exclude .pytest_cache \
  --exclude __pycache__ --exclude htmlcov --exclude .coverage \
  --exclude .env --exclude .env.agent --exclude .env.xray \
  ./ user@agent-host:~/rkn-blocks-monitoring-agent/ && \
ssh user@agent-host "cd ~/rkn-blocks-monitoring-agent && \
  docker compose -f docker-compose.agent.yml build rknmon-agent && \
  docker compose -f docker-compose.agent.yml up -d --force-recreate rknmon-agent"

# check Xray on the agent host
ssh user@agent-host 'docker exec rknmon-agent sh -lc "for p in 11001 11002; do \
  curl -sS -o /dev/null -w %{http_code} --max-time 15 \
  --proxy socks5h://127.0.0.1:\${p} https://cp.cloudflare.com/; done"'

# DB sanity
sudo docker exec rknmon_db psql -U rknmon -d rknmon -P pager=off \
  -c "SELECT COALESCE(subscription_name,'default'), count(*) FROM xray_probe_results \
      WHERE checked_at > now() - interval '1 hour' GROUP BY 1;"
```

## НЕ ДЕЛАЙ

- ❌ не пиши реальные subscription-ссылки, API keys, passwords в README, в чат, в git
- ❌ не запускай Xray с поднятым TUN / iptables redirect
- ❌ не меняй default route на агенте
- ❌ не коммить `.env`, `.env.agent`, `.env.xray`
- ❌ не удаляй subscription_name column из БД (миграция идёт через `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`)
