# Edge agent (Docker)

1. Install Docker on the agent host (VPS, home server, Raspberry Pi, etc.):
   - `sudo apt update`
   - `sudo apt install -y docker.io docker-compose-plugin git`
   - `sudo usermod -aG docker $USER`
   - relogin or run `newgrp docker`
2. Copy repo to `/opt/rkn-blocks-monitoring`
3. Create agent env file:
   - `cp .env.agent.example .env.agent`
   - edit `CENTRAL_API_URL`, `NODE_API_KEY`, `AGENT_NAME`
4. Create Xray env file:
   - `cp .env.xray.example .env.xray`
   - put subscription links into `XRAY_SUBSCRIPTION_URLS`
   - put safe display names into `XRAY_SUBSCRIPTION_NAMES` in the same order; these names are used as the Grafana `Subscription` filter
5. Register / heartbeat flow:
   - agent uses outbound HTTPS only
   - `POST /agent/register`
   - `POST /agent/heartbeat`
   - `GET /agent/targets`
   - `POST /agent/results`
6. Build and start:
   - `docker compose -f docker-compose.agent.yml up -d --build`
7. One-shot test:
   - `docker compose -f docker-compose.agent.yml run --rm rknmon-agent --once`
8. Logs:
   - `docker compose -f docker-compose.agent.yml logs -f rknmon-agent`
