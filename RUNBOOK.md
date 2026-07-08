# RKN Blocks Monitoring — Operations Runbook

Runbook для запуска, проверки и диагностики central-сервера и edge-агентов.

## 1. Central: dev start

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

cp .env.example .env
docker compose up -d db
uvicorn rknmon.api.main:app --reload --host 127.0.0.1 --port 23234
```

Проверка:

```bash
curl -fsS http://127.0.0.1:23234/health
curl -fsS http://127.0.0.1:23234/metrics/ | head
```

## 2. Central: prod start

```bash
cp .env.example .env
# edit .env: POSTGRES_PASSWORD, API_KEY, GRAFANA_ADMIN_PASSWORD, GRAFANA_ROOT_URL

sudo docker build -t rknmon:1.0.0 .
sudo docker compose -f docker-compose.prod.yml up -d
```

`docker-compose.prod.yml` использует image `rknmon:1.0.0`; если образ не собран заранее, `up` завершится ошибкой pull/build.

### Что поднимается в prod

| Сервис | Доступ | Описание |
|---|---|---|
| `rknmon_db` | `127.0.0.1:5432` на host | PostgreSQL |
| `rknmon_app` | `0.0.0.0:23234` на host → `:8000` в container | FastAPI + scheduler + `/metrics` |
| `rknmon_prometheus` | только Docker network | Scrape `http://app:8000/metrics` |
| `rknmon_grafana` | только Docker network | Dashboards, доступ через nginx |
| `rknmon_nginx` | `0.0.0.0:8443` | TLS reverse proxy |

Production policy: публичный вход идёт через nginx `:8443`; host app port `:23234` и остальные служебные порты должны быть закрыты firewall/IP whitelist.

### Проверка prod

```bash
sudo docker compose -f docker-compose.prod.yml ps
curl -fsS http://127.0.0.1:23234/health
sudo docker compose -f docker-compose.prod.yml exec prometheus \
  wget -qO- http://app:8000/metrics | head
```

Grafana доступна через nginx route из `monitoring/nginx/nginx.conf.example`, а не через прямой host port `:3000`.

## 3. Central: управление

```bash
sudo docker compose -f docker-compose.prod.yml logs -f app
sudo docker compose -f docker-compose.prod.yml logs -f nginx
sudo docker compose -f docker-compose.prod.yml logs -f grafana
sudo docker compose -f docker-compose.prod.yml restart app
sudo docker compose -f docker-compose.prod.yml up -d --force-recreate app
```

Пересборка приложения:

```bash
sudo docker build -t rknmon:1.0.0 .
sudo docker compose -f docker-compose.prod.yml up -d --force-recreate app
```

## 4. Agent: установка invite-командой

На central/admin машине:

```bash
export RKNMON_CENTRAL_URL=https://monitor.example.com
export RKNMON_ADMIN_API_KEY=<central-api-key>

rknmon-admin agent-invite --name friend-msk --location msk --provider mts --modes dpi
```

На agent host:

```bash
curl -fsSL https://monitor.example.com/install-agent.sh | sudo bash -s -- \
  --central https://monitor.example.com \
  --token <invite-token>
```

Рабочий каталог installer: `/opt/rknmon-agent`.

## 5. Agent: ручное управление

```bash
cd /opt/rkn-blocks-monitoring  # или другой каталог manual deploy

docker compose -f docker-compose.agent.yml ps
docker compose -f docker-compose.agent.yml logs -f rknmon-agent
docker compose -f docker-compose.agent.yml logs -f rknmon-xray
docker compose -f docker-compose.agent.yml restart rknmon-agent
```

One-shot cycle:

```bash
docker compose -f docker-compose.agent.yml run --rm rknmon-agent --once
```

Обновление manual deploy:

```bash
git pull --ff-only
docker compose -f docker-compose.agent.yml up -d --build --force-recreate rknmon-agent
```

## 6. Метрики

Приложение экспортирует Prometheus metrics на `/metrics/`:

- `rknmon_active_targets`
- `rknmon_targets_by_state{state}`
- `rknmon_events_total{event_type}`
- `rknmon_probe_latest_response_ms{target_id,domain,probe_type}`
- `rknmon_xray_profile_status{agent,subscription,profile,protocol,transport,server}`
- `rknmon_xray_profile_latency_ms{agent,subscription,profile,protocol,transport,server}`
- `rknmon_xray_profile_errors_total{agent,subscription,profile,protocol,transport,server,error_type}`

Проверка свежих Xray labels:

```bash
curl -fsS http://127.0.0.1:23234/metrics/ | grep rknmon_xray_profile_status
```

## 7. База данных

```bash
sudo docker exec rknmon_db psql -U rknmon -d rknmon -P pager=off \
  -c "SELECT status, count(*) FROM xray_probe_results WHERE checked_at > now() - interval '1 hour' GROUP BY status;"

sudo docker exec rknmon_db psql -U rknmon -d rknmon -P pager=off \
  -c "SELECT COALESCE(subscription_name,'default'), count(*), max(checked_at) FROM xray_probe_results GROUP BY 1;"
```

Backup:

```bash
DATABASE_URL=postgresql://... ./scripts/backup.sh
```

## 8. Synthetic/load test

```bash
DATABASE_URL=postgresql://... python scripts/generate_synthetic.py 500
locust -f scripts/locustfile.py --host http://127.0.0.1:23234
```

## 9. Common issues

1. **DB connection refused** — проверить `DATABASE_URL`, healthcheck `rknmon_db`, container network.
2. **403 on API calls** — проверить `X-API-Key` для admin API или `X-Node-API-Key` для agent API.
3. **Public installer отдаёт 404** — проверить, что central app содержит routes `/install-agent.sh` и `/docker-compose.agent.public.yml`, а nginx проксирует их к app.
4. **Prometheus не видит app** — из контейнера Prometheus выполнить `wget -qO- http://app:8000/metrics`.
5. **Grafana dashboard пустой** — проверить datasource UIDs: Prometheus `PBFA97CFB590B2093`, Postgres `grafana-postgres`.
6. **Xray agent не отправляет данные**:
   - `docker logs -f rknmon-agent`
   - `docker logs -f rknmon-xray`
   - проверить `.env.xray`: `XRAY_SUBSCRIPTION_URLS` и `XRAY_SUBSCRIPTION_NAMES` одинаковой длины
   - проверить SOCKS-порты внутри `rknmon-agent`
7. **Image pull зависает на слабом/цензурируемом agent host** — заранее скачать image на другой машине и передать через `docker save` / `docker load`.

## 10. ARMv7 image workaround

```bash
sudo docker pull --platform linux/arm/v7 IMAGE:TAG
sudo docker save IMAGE:TAG | gzip -1 > /tmp/img.tar.gz
scp /tmp/img.tar.gz user@agent-host:/tmp/img.tar.gz
ssh user@agent-host 'docker load -i /tmp/img.tar.gz'
```

## 11. Тесты

```bash
source .venv/bin/activate
pytest -q
ruff check .
python -m compileall src tests
```

## 12. Секреты

- `.env`, `.env.agent`, `.env.xray` не должны попадать в git.
- API keys, invite tokens, passwords и subscription URLs не писать в README, issues, commit messages или чат.
- В документах использовать `<redacted>` / `<...>` placeholders.
