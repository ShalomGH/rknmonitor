# AGENTS.md

> Файл, который LLM-агенты (Claude Code, Codex, Hermes и т.п.) должны прочитать **первым** в этом репозитории. Даёт минимум контекста и указывает на полный LLM-context.

## Суть

`rkn-blocks-monitoring` — FastAPI central + edge-агенты для мониторинга РКН-блокировок и Xray-профилей.

- Repo: локальная рабочая копия проекта
- Central: сервер `monitor.example.com`, `nginx :8443 → app :8000` внутри Docker; host port `:23234` используется для прямой локальной проверки app
- Edge agent: Linux host/container (amd64/arm64/armv7), outbound-only HTTPS к central API
- Стек: Python 3.12, FastAPI, asyncpg, aiohttp, Docker

## Полный контекст

📖 **Перед серьёзной работой читай `PROJECT_CONTEXT.md`** (структура, история, инварианты, runbook, env vars, pitfalls, соглашения).

⚡ Для быстрого старта — `QUICKREF.md` (TL;DR, ключевые пути и команды).

🗂 Структурированный manifest — `PROJECT_MANIFEST.md` (LLM-readable manifest в формате «что/где/как»).

## Не делай

- ❌ не сохраняй API keys, tokens, subscription links, passwords в чат/коммиты/память — заменять на `<redacted>`
- ❌ не поднимай TUN/VPN/iptables redirect на агенте — Xray должен работать только через SOCKS `127.0.0.1`
- ❌ не коммить `.env`, `.env.agent`, `.env.xray`

## Связанные skills

- `devops/censorship-monitoring` — общий DPI/RKN/Xray playbook
- `devops/rpi-home-access` — частный runbook для домашнего Raspberry Pi/ARMv7
- `devops/monitoring-stack-docker` — Prometheus + Grafana deploy
- `devops/secure-server-run` — iptables, security hardening
- `superpowers:subagent-driven-development` — multi-agent реализация фич
- `superpowers:executing-plans` — выполнение планов из `docs/superpowers/plans/`
