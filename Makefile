# RKN monitoring — admin / day-to-day operations.
#
# Most day-to-day work for the operator (you) is minting invites for
# friends and revoking them. Everything that talks to /admin/agents/*
# goes through `rknmon-admin`, which uses the central API key.
#
# Usage:
#   make agent-invite NAME=friend-msk LOCATION=msk PROVIDER=mts
#   make agent-invite-xray NAME=friend-spb LOCATION=spb PROVIDER=rt \
#         SUB1=https://sub.example/a SUB_NAME1=only-cry \
#         SUB2=https://sub.example/b SUB_NAME2=antizapret
#   make agent-list
#   make agent-revoke ID=7
#   make test

# Where the central API lives. Override on the command line:
#   make agent-invite NAME=x CENTRAL=https://mon.example.com
CENTRAL ?= https://monitor.example.com
export RKNMON_CENTRAL_URL ?= $(CENTRAL)
# Central admin API key (X-API-Key). Loaded from .env if present.
API_KEY ?= $(shell grep -E '^API_KEY=' .env 2>/dev/null | cut -d= -f2-)
export RKNMON_ADMIN_API_KEY ?= $(API_KEY)
export API_KEY

PYTHON ?= python3
VENV ?= .venv
PY    = $(VENV)/bin/python

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# -------- agent invites (one-command friend install) --------

.PHONY: agent-invite
agent-invite: ## Mint a DPI-only invite: NAME=friendly-id [LOCATION=] [PROVIDER=] [EXPIRES_HOURS=168] [MAX_USES=1] [NOTE=]
	@if [ -z "$(NAME)" ]; then echo "ERROR: NAME= is required (e.g. NAME=friend-msk)" >&2; exit 2; fi
	$(PY) -m rknmon.admin.cli agent-invite \
	    --name "$(NAME)" \
	    $(if $(LOCATION),--location "$(LOCATION)") \
	    $(if $(PROVIDER),--provider "$(PROVIDER)") \
	    --modes dpi \
	    --expires-in-hours $(or $(EXPIRES_HOURS),168) \
	    --max-uses $(or $(MAX_USES),1) \
	    $(if $(NOTE),--note "$(NOTE)")

.PHONY: agent-invite-xray
agent-invite-xray: ## Mint a DPI+Xray invite with subscriptions baked in
	@if [ -z "$(NAME)" ]; then echo "ERROR: NAME= is required" >&2; exit 2; fi
	@if [ -z "$(SUB1)" ]; then echo "ERROR: SUB1= is required (subscription URL)" >&2; exit 2; fi
	$(PY) -m rknmon.admin.cli agent-invite \
	    --name "$(NAME)" \
	    $(if $(LOCATION),--location "$(LOCATION)") \
	    $(if $(PROVIDER),--provider "$(PROVIDER)") \
	    --modes dpi,xray \
	    --xray-sub "$(SUB1)$(if $(SUB2),,)$(if $(SUB2),$(COMMA)$(SUB2))" \
	    --xray-name "$(SUB_NAME1)$(if $(SUB2),,)$(if $(SUB2),$(COMMA)$(SUB_NAME2))" \
	    --expires-in-hours $(or $(EXPIRES_HOURS),168) \
	    --max-uses $(or $(MAX_USES),1)
COMMA=,

.PHONY: agent-list
agent-list: ## List active (unused, unexpired) invites
	$(PY) -m rknmon.admin.cli agent-list-invites

.PHONY: agent-list-all
agent-list-all: ## List all invites (including used/expired)
	$(PY) -m rknmon.admin.cli agent-list-invites-all

.PHONY: agent-revoke
agent-revoke: ## Revoke an unused invite: ID=<invite_id>
	@if [ -z "$(ID)" ]; then echo "ERROR: ID= is required" >&2; exit 2; fi
	$(PY) -m rknmon.admin.cli agent-revoke-invite $(ID)

# -------- dev / test --------

.PHONY: test
test: ## Run pytest
	$(PY) -m pytest -q

.PHONY: lint
lint: ## Sanity-check the install script and CLI help text
	bash -n deploy/install-agent.sh
	$(PY) -m rknmon.admin.cli --help
