# Edge agent deployment

Edge agent — удалённая точка наблюдения для `rkn-blocks-monitoring`. Он запускается на любой Linux-ноде с Docker: VPS, домашний сервер, Raspberry Pi, mini-PC. Агент не требует входящих портов и отправляет результаты в central API по outbound HTTPS.

## Что запускается

| Контейнер | Назначение |
|---|---|
| `rknmon-agent` | Регистрируется в central, получает targets, выполняет HTTP/DNS/DPI/Xray probes и отправляет результаты |
| `rknmon-xray` | Sidecar для Xray-профилей; ждёт `/config/xray.generated.json` и поднимает SOCKS-порты `127.0.0.1:11001+` |

`rknmon-agent` использует `network_mode: service:rknmon-xray`, поэтому SOCKS-порты доступны ему как `127.0.0.1`. TUN/VPN/iptables redirect не используются.

## Вариант A: установка одной командой через invite

1. Администратор central создаёт invite:

```bash
export RKNMON_CENTRAL_URL=https://monitor.example.com
export RKNMON_ADMIN_API_KEY=<central-api-key>

rknmon-admin agent-invite \
  --name friend-msk \
  --location msk \
  --provider mts \
  --modes dpi
```

Для Xray добавить `xray` mode и безопасные имена подписок:

```bash
rknmon-admin agent-invite \
  --name friend-spb \
  --location spb \
  --provider rostelecom \
  --modes dpi,xray \
  --xray-sub 'https://sub.example/one,https://sub.example/two' \
  --xray-name 'sub-one,sub-two'
```

2. На agent host выполнить команду, которую напечатал CLI:

```bash
curl -fsSL https://monitor.example.com/install-agent.sh | sudo bash -s -- \
  --central https://monitor.example.com \
  --token <invite-token>
```

Installer создаёт `/opt/rknmon-agent`, скачивает `docker-compose.agent.public.yml`, обменивает token через `POST /agent/bootstrap`, записывает `.env.agent` / `.env.xray` с правами `0600` и запускает compose stack.

## Вариант B: ручной deploy из репозитория

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
```

Отредактировать `.env.agent`:

```bash
CENTRAL_API_URL=https://monitor.example.com
NODE_API_KEY=<per-node-key>
AGENT_NAME=friend-msk
AGENT_LOCATION=msk
AGENT_PROVIDER=mts
DPI_ENABLED=true
XRAY_ENABLED=false
```

Если нужен Xray, отредактировать `.env.xray`:

```bash
XRAY_ENABLED=true
XRAY_SUBSCRIPTION_URLS=https://example.invalid/sub-one,https://example.invalid/sub-two
XRAY_SUBSCRIPTION_NAMES=sub-one,sub-two
XRAY_TEST_URL=https://cp.cloudflare.com/
XRAY_SOCKS_START_PORT=11001
```

Запуск:

```bash
docker compose -f docker-compose.agent.yml up -d --build
```

## Проверка

```bash
docker compose -f docker-compose.agent.yml ps
docker compose -f docker-compose.agent.yml logs -f rknmon-agent
docker compose -f docker-compose.agent.yml logs -f rknmon-xray
```

One-shot cycle:

```bash
docker compose -f docker-compose.agent.yml run --rm rknmon-agent --once
```

Проверка SOCKS внутри agent container:

```bash
docker exec rknmon-agent sh -lc '
for p in 11001 11002; do
  curl -sS -o /dev/null -w "%{http_code}\n" --max-time 15 \
    --proxy socks5h://127.0.0.1:${p} https://cp.cloudflare.com/
done
'
```

## Обновление manual agent

```bash
cd /opt/rkn-blocks-monitoring
git pull --ff-only
docker compose -f docker-compose.agent.yml up -d --build --force-recreate rknmon-agent
```

## Безопасность

- Не коммитить `.env.agent` и `.env.xray`.
- Не отправлять реальные `NODE_API_KEY`, invite tokens и subscription URLs в чат или issue tracker.
- Не открывать входящие порты на agent host.
- Не включать TUN/VPN mode для Xray; проект использует только явные SOCKS-probe запросы.
