#!/usr/bin/env bash
# RKN monitoring agent one-command installer.
#
# This script is served at <CENTRAL>/install-agent.sh and pulled by the
# friend via:
#
#   curl -fsSL https://mon.example.com/install-agent.sh | sudo bash -s -- \
#     --central https://mon.example.com \
#     --token <invite-token>
#
# It does NOT take or print API keys, subscription URLs, or any other
# secret. The only secret the user types or pastes is the short-lived
# invite token. The real NODE_API_KEY is minted by central on /agent/bootstrap
# and written into .env.agent by this script.
#
# The script is safe to re-run: it overwrites .env.agent and .env.xray
# with the values returned by /agent/bootstrap, then re-creates the
# containers.

set -euo pipefail

CENTRAL=""
TOKEN=""
NAME=""
LOCATION=""
PROVIDER=""
MODES="dpi"
ASSUME_YES=0
SKIP_DOCKER=0
INSTALL_DIR="/opt/rknmon-agent"
COMPOSE_FILE_URL_OVERRIDE=""

print_usage() {
  cat <<'USAGE'
Usage:
  install-agent.sh --central <URL> --token <INVITE_TOKEN> [options]

Required:
  --central URL         Central API base URL (e.g. https://mon.example.com)
  --token TOKEN         Single-use invite token from the central admin

Optional:
  --name NAME           Override agent name (defaults to the one bound to the invite)
  --location LOC        Free-text location label
  --provider ISP        Free-text provider/ISP label
  --modes LIST          Comma-separated modes: dpi, xray, dpi,xray
  --install-dir DIR     Where to put .env.agent and docker-compose.agent.public.yml
                        (default: /opt/rknmon-agent)
  --yes                 Don't prompt for non-essential confirmations
  --skip-docker         Assume Docker is already installed
  --compose-url URL     Override docker-compose.agent.public.yml download URL
                        (default: <central>/docker-compose.agent.public.yml)

Examples:
  install-agent.sh --central https://mon.example.com --token abcdef1234
USAGE
}

err() { echo "[install-agent] ERROR: $*" >&2; }
log() { echo "[install-agent] $*"; }

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --central)            CENTRAL="${2:-}"; shift 2;;
      --token)              TOKEN="${2:-}"; shift 2;;
      --name)               NAME="${2:-}"; shift 2;;
      --location)           LOCATION="${2:-}"; shift 2;;
      --provider)           PROVIDER="${2:-}"; shift 2;;
      --modes)              MODES="${2:-}"; shift 2;;
      --install-dir)        INSTALL_DIR="${2:-}"; shift 2;;
      --yes)                ASSUME_YES=1; shift;;
      --skip-docker)        SKIP_DOCKER=1; shift;;
      --compose-url)        COMPOSE_FILE_URL_OVERRIDE="${2:-}"; shift 2;;
      -h|--help)            print_usage; exit 0;;
      *) err "Unknown argument: $1"; print_usage; exit 2;;
    esac
  done

  if [[ -z "$CENTRAL" || -z "$TOKEN" ]]; then
    err "--central and --token are required"
    print_usage
    exit 2
  fi
  CENTRAL="${CENTRAL%/}"
}

require_root() {
  if [[ $EUID -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
      log "Re-running under sudo..."
      exec sudo --preserve-env=HTTP_PROXY,HTTPS_PROXY,NO_PROXY \
        "$0" "$@"
    else
      err "Please run as root or install sudo"
      exit 1
    fi
  fi
}

detect_os() {
  if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    OS_ID="${ID:-}"
    OS_VERSION_CODENAME="${VERSION_CODENAME:-}"
  else
    err "Cannot detect OS: /etc/os-release missing"
    exit 1
  fi
  case "$OS_ID" in
    ubuntu|debian|raspbian) ;;
    *)
      err "Unsupported OS: $OS_ID. This script supports Debian-family only."
      exit 1
      ;;
  esac
}

install_docker() {
  if [[ "$SKIP_DOCKER" -eq 1 ]]; then
    return 0
  fi
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    return 0
  fi
  log "Installing Docker..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends ca-certificates curl gnupg jq
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/$OS_ID/gpg \
    | gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/$OS_ID \
    $OS_VERSION_CODENAME stable" >/etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  if ! docker compose version >/dev/null 2>&1; then
    err "docker compose plugin not available after install"
    exit 1
  fi
}

prepare_install_dir() {
  mkdir -p "$INSTALL_DIR"
  cd "$INSTALL_DIR"
  log "Install dir: $INSTALL_DIR"
}

download_compose_file() {
  local url="${COMPOSE_FILE_URL_OVERRIDE:-$CENTRAL/docker-compose.agent.public.yml}"
  log "Fetching docker-compose.agent.public.yml from $url"
  if ! curl -fsSL "$url" -o docker-compose.agent.public.yml; then
    err "Failed to download $url"
    exit 1
  fi
  chmod 0644 docker-compose.agent.public.yml
}

bootstrap() {
  local payload
  payload=$(jq -n \
    --arg token "$TOKEN" \
    --arg name  "$NAME" \
    --arg location "$LOCATION" \
    --arg provider "$PROVIDER" \
    --arg agent_version "0.1.0" \
    '{
       token: $token,
       name: $name,
       location: ($location | select(. != "")),
       provider: ($provider | select(. != "")),
       agent_version: $agent_version
     }')

  log "Exchanging invite for agent credentials..."
  local resp
  resp=$(curl -fsSL \
    -H "Content-Type: application/json" \
    -X POST \
    --data "$payload" \
    "$CENTRAL/agent/bootstrap")

  # `node_api_key` is the ONLY long-lived secret minted by this run.
  # The install script keeps it in .env.agent (chmod 600) and never
  # echoes it on success. The friend should not see it in chat.
  local node_api_key central_url agent_name modes_csv
  central_url=$(echo "$resp"   | jq -r '.central_api_url')
  node_api_key=$(echo "$resp"  | jq -r '.node_api_key')
  agent_name=$(echo "$resp"    | jq -r '.agent_name')
  modes_csv=$(echo "$resp"     | jq -r '.modes | join(",")')

  if [[ -z "$node_api_key" || "$node_api_key" == "null" ]]; then
    err "Bootstrap failed; central did not return node_api_key"
    echo "$resp" >&2
    exit 1
  fi

  log "Got node_api_key for agent '$agent_name' (modes: $modes_csv)"

  write_env_agent "$central_url" "$node_api_key" "$agent_name"
  write_env_xray_from_invite "$resp"

  # Best-effort cleanup: keep token in memory only.
  unset node_api_key
}

write_env_agent() {
  local central_url="$1" node_api_key="$2" agent_name="$3"
  local location provider
  location=$( [[ -n "$LOCATION" ]] && echo "$LOCATION" || echo "$agent_name" )
  provider=$( [[ -n "$PROVIDER" ]] && echo "$PROVIDER" || echo "unknown" )

  local xray_enabled="false"
  case ",$MODES," in
    *",xray,"*) xray_enabled="true" ;;
  esac
  local dpi_enabled="true"
  case ",$MODES," in
    *",xray-only,"*) dpi_enabled="false" ;;
  esac

  log "Writing .env.agent (chmod 600)"
  {
    printf 'CENTRAL_API_URL=%s\n' "$central_url"
    printf 'NODE_API_KEY=%s\n' "$node_api_key"
    printf 'AGENT_NAME=%s\n' "$agent_name"
    printf 'AGENT_LOCATION=%s\n' "$location"
    printf 'AGENT_PROVIDER=%s\n' "$provider"
    printf 'AGENT_VERSION=0.1.0\n'
    printf 'PUBLIC_IP=\n'
    printf 'PROBE_INTERVAL_SECONDS=300\n'
    printf 'PROBE_CONCURRENCY=20\n'
    printf 'DPI_ENABLED=%s\n' "$dpi_enabled"
    printf 'DPI_TARGETS=YouTube=www.youtube.com,Discord=discord.com,Telegram=api.telegram.org,GitHub=github.com,Cloudflare=cloudflare.com\n'
    printf 'DPI_WHITELISTED_URLS=https://ya.ru/,https://vk.ru/,https://max.ru/\n'
    printf 'DPI_REGULAR_URLS=https://github.com/,https://www.google.com/,https://ru.wikipedia.org/\n'
    printf 'DPI_TIMEOUT_SECONDS=10\n'
    printf 'DPI_L4_PAYLOAD_BYTES=65536\n'
    printf 'XRAY_ENABLED=%s\n' "$xray_enabled"
    printf 'XRAY_TEST_URL=https://cp.cloudflare.com/\n'
    printf 'XRAY_SOCKS_START_PORT=11001\n'
    printf 'XRAY_CONFIG_PATH=/config/xray.generated.json\n'
    printf 'XRAY_WAIT_FOR_SOCKS=true\n'
    printf 'XRAY_READY_TIMEOUT_SECONDS=90\n'
    printf 'LOG_LEVEL=INFO\n'
  } > .env.agent
  chmod 600 .env.agent
}

write_env_xray_from_invite() {
  # Subscriptions are baked into the invite row by the admin at mint time.
  # The friend does NOT pass them on the command line — they arrive in
  # the bootstrap response. We strip them out of .env.agent for safety
  # and write them only to .env.xray.
  #
  # The caller (bootstrap) passes the bootstrap response JSON via $1 so
  # we don't need to make a second /agent/bootstrap call (which would
  # fail because the invite was already consumed).
  local resp="$1"

  local urls names
  urls=$(printf '%s' "$resp" | jq -r '.xray_subscription_urls | join(",")')
  names=$(printf '%s' "$resp" | jq -r '.xray_subscription_names | join(",")')

  if [[ -z "$urls" || "$urls" == "null" ]]; then
    log "No Xray subscriptions baked into this invite; .env.xray will be empty"
    : > .env.xray
    chmod 600 .env.xray
    return 0
  fi

  log "Writing .env.xray with subscriptions: $names"
  {
    printf 'XRAY_ENABLED=true\n'
    printf 'XRAY_SUBSCRIPTION_URLS=%s\n' "$urls"
    printf 'XRAY_SUBSCRIPTION_NAMES=%s\n' "$names"
    printf 'XRAY_TEST_URL=https://cp.cloudflare.com/\n'
    printf 'XRAY_SOCKS_START_PORT=11001\n'
    printf 'XRAY_CONFIG_PATH=/config/xray.generated.json\n'
    printf 'XRAY_WAIT_FOR_SOCKS=true\n'
    printf 'XRAY_READY_TIMEOUT_SECONDS=90\n'
  } > .env.xray
  chmod 600 .env.xray
}

bring_up() {
  log "Starting containers..."
  docker compose -f docker-compose.agent.public.yml pull
  docker compose -f docker-compose.agent.public.yml up -d --force-recreate
  log "Containers up. Recent logs:"
  docker compose -f docker-compose.agent.public.yml logs --tail=40 rknmon-agent || true
}

print_done() {
  cat <<DONE

[install-agent] DONE.

Agent installed at: $INSTALL_DIR
- Compose file:   $INSTALL_DIR/docker-compose.agent.public.yml
- Config:         $INSTALL_DIR/.env.agent  (chmod 600)
- Xray config:    $INSTALL_DIR/.env.xray   (chmod 600, if xray mode)

Useful commands:
  cd $INSTALL_DIR
  docker compose -f docker-compose.agent.public.yml logs -f rknmon-agent
  docker compose -f docker-compose.agent.public.yml ps
  docker compose -f docker-compose.agent.public.yml restart rknmon-agent

If the central dashboard does not show this agent within 60 seconds,
check:
  docker compose -f docker-compose.agent.public.yml logs rknmon-agent
DONE
}

main() {
  parse_args "$@"
  require_root "$@"
  detect_os
  install_docker
  prepare_install_dir
  download_compose_file
  bootstrap
  bring_up
  print_done
}

main "$@"
