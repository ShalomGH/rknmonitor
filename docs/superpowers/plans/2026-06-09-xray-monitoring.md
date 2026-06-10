# Xray Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add outbound-only Xray subscription/profile monitoring to the existing RKN monitoring project.

**Architecture:** Agents fetch configured Xray subscription URLs, parse profile links, generate a deterministic local Xray client config with one SOCKS inbound per profile, probe test URLs through those local SOCKS ports, and push summarized results to the central API. Central stores results in PostgreSQL and exposes Prometheus metrics for profile status/latency/errors.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, aiohttp, pytest, Docker agent.

---

### Task 1: Subscription parsing and Xray config model

**Files:**
- Create: `src/rknmon/agent/xray.py`
- Test: `tests/test_xray_subscription.py`

- [ ] Write failing tests for parsing base64 subscriptions containing `vless://`, `vmess://`, `trojan://`, `ss://` links.
- [ ] Run: `source .venv/bin/activate && pytest tests/test_xray_subscription.py -v`; expected fail: module missing.
- [ ] Implement `XrayProfile`, `parse_subscription_text()`, `load_profiles_from_urls()`, `build_xray_config()`.
- [ ] Run the same test; expected pass.

### Task 2: Central ingest endpoint and schema

**Files:**
- Modify: `src/rknmon/db_schema.py`
- Modify: `src/rknmon/models/schemas.py`
- Modify: `src/rknmon/api/agents.py`
- Modify: `src/rknmon/custom_metrics.py`
- Test: `tests/test_xray_agents_api.py`

- [ ] Write failing API test for `POST /agent/xray-results` storing profile probe rows.
- [ ] Run targeted test; expected fail: endpoint/schema missing.
- [ ] Add `xray_profiles` and `xray_probe_results` tables.
- [ ] Add Pydantic models `XrayProbeIn` and `XrayProbeBatchIn`.
- [ ] Add Prometheus gauges/counters for profile status, latency and errors.
- [ ] Implement endpoint with node API-key auth reused from existing agent endpoints.
- [ ] Run targeted test; expected pass.

### Task 3: Agent runner integration

**Files:**
- Modify: `src/rknmon/agent/config.py`
- Modify: `src/rknmon/agent/client.py`
- Modify: `src/rknmon/agent/runner.py`
- Modify: `src/rknmon/agent/cli.py`
- Test: `tests/test_xray_agent_runner.py`

- [ ] Write failing runner test proving subscription profiles are probed and submitted.
- [ ] Run targeted test; expected fail: runner has no Xray integration.
- [ ] Add `XRAY_SUBSCRIPTION_URLS`, `XRAY_TEST_URL`, `XRAY_SOCKS_START_PORT`, `XRAY_CONFIG_PATH`, `XRAY_ENABLED` settings.
- [ ] Implement `run_xray_probe_cycle()` with injectable fetch/probe functions.
- [ ] CLI `--xray-only` and `--write-xray-config` flags.
- [ ] Run targeted test; expected pass.

### Task 4: Verification

**Files:**
- Existing test suite.

- [ ] Run targeted Xray tests.
- [ ] Run existing agent/API tests touched by the change.
- [ ] Run full pytest if feasible.
- [ ] Report actual command outputs and any blockers.
