import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Force middleware to think the install does not allow direct registration.
os.environ.setdefault("RKNMON_ALLOW_DIRECT_REGISTRATION", "false")

from fastapi.testclient import TestClient  # noqa: E402

from rknmon.api.main import app  # noqa: E402
from rknmon.config import settings as settings_module  # noqa: E402
from rknmon.models.schemas import AgentInviteCreateIn  # noqa: E402

client = TestClient(app)

ADMIN_HEADERS = {"X-API-Key": "test-admin-key-1"}
# Pin the admin API key in the singleton settings for these tests so they
# don't depend on the local .env. Other test files may have already loaded
# settings from the env, so override the attribute on the instance directly.
settings_module.settings.api_key = "test-admin-key-1"


# --- pure validation helpers (no DB) ---


def test_validate_modes_defaults_to_dpi():
    from rknmon.api.agent_invites import validate_modes

    assert validate_modes([]) == ["dpi"]
    assert validate_modes([""]) == ["dpi"]
    assert validate_modes(["dpi", "xray"]) == ["dpi", "xray"]


def test_validate_modes_rejects_unknown():
    from rknmon.api.agent_invites import validate_modes

    with pytest.raises(ValueError, match="Unknown mode"):
        validate_modes(["dpi", "totally-bogus"])


def test_validate_subscription_pairs_requires_equal_length():
    from rknmon.api.agent_invites import validate_subscription_pairs

    # Both filtered to non-empty — unequal lengths => ValueError.
    with pytest.raises(ValueError, match="must have the same length"):
        validate_subscription_pairs(
            ["https://a/sub", "https://b/sub"],
            ["only-a"],
        )

    # One side empty after filtering => the surviving side must also be
    # empty or ValueError.
    with pytest.raises(ValueError, match="must have the same length"):
        validate_subscription_pairs(
            ["https://a/sub"],
            [],
        )

    # Equal length => OK
    urls, names = validate_subscription_pairs(
        ["https://a/sub", "https://b/sub"],
        ["a", "b"],
    )
    assert urls == ["https://a/sub", "https://b/sub"]
    assert names == ["a", "b"]


def test_validate_subscription_pairs_rejects_too_many():
    from rknmon.api.agent_invites import validate_subscription_pairs

    urls = [f"https://x/sub{i}" for i in range(33)]
    names = [f"sub{i}" for i in range(33)]
    with pytest.raises(ValueError, match="max 32"):
        validate_subscription_pairs(urls, names)


# --- token / key shape ---


def test_token_is_long_and_url_safe():
    from rknmon.api.agent_invites import generate_token, generate_node_api_key

    tok = generate_token()
    assert len(tok) >= 32
    assert all(c in "0123456789abcdef" for c in tok)
    key = generate_node_api_key()
    assert key.startswith("rnk_")
    assert len(key) > 30


# --- admin endpoint: require X-API-Key ---


def test_admin_invites_require_api_key():
    response = client.post(
        "/admin/agents/invites",
        json={"name": "friend-1"},
    )
    assert response.status_code == 403


def test_admin_invites_validates_input():
    response = client.post(
        "/admin/agents/invites",
        json={"name": "friend-1", "expires_in_hours": 0},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 400
    assert "expires_in_hours" in response.json()["detail"]


def test_admin_invites_rejects_unknown_mode():
    response = client.post(
        "/admin/agents/invites",
        json={"name": "friend-1", "modes": ["nope"]},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 400


# --- admin endpoint: create + list + revoke (mocked DB) ---


@patch("rknmon.api.agent_invites_routes.create_invite", new_callable=AsyncMock)
def test_admin_invite_round_trip(mock_create):
    mock_create.return_value = {
        "id": 1,
        "token": "tok",
        "name": "friend-msk",
        "location": "msk",
        "provider": "mts",
        "modes": ["dpi"],
        "xray_subscription_urls": [],
        "xray_subscription_names": [],
        "xray_test_url": "https://cp.cloudflare.com/",
        "expires_at": "2026-06-17T00:00:00Z",
        "max_uses": 1,
        "uses": 0,
        "note": None,
        "created_by": "admin",
        "created_at": "2026-06-10T00:00:00Z",
    }
    response = client.post(
        "/admin/agents/invites",
        json={"name": "friend-msk", "location": "msk", "provider": "mts"},
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "friend-msk"
    assert body["token"] == "tok"


@patch("rknmon.api.agent_invites_routes.revoke_invite", new_callable=AsyncMock)
def test_admin_revoke_invite(mock_revoke):
    mock_revoke.return_value = True
    response = client.delete(
        "/admin/agents/invites/1",
        headers=ADMIN_HEADERS,
    )
    assert response.status_code == 200
    assert response.json() == {"revoked": True, "id": 1}


# --- /agent/register: invite-only by default ---


def test_register_without_invite_is_rejected_by_default():
    # fetchrow would otherwise hit the DB; we want to assert the *auth* branch
    # is reached when no pre-existing node is found for the key.
    from rknmon.api import agents as agents_mod

    with patch.object(agents_mod, "fetchrow", new_callable=AsyncMock, return_value=None):
        response = client.post(
            "/agent/register",
            headers={"X-Node-API-Key": "absent-key"},
            json={"name": "rogue"},
        )
    assert response.status_code == 403
    assert "invite-based" in response.json()["detail"]


def test_register_with_existing_key_returns_existing():
    from rknmon.api import agents as agents_mod

    fake_existing = {
        "id": 11,
        "name": "friend-msk",
        "is_active": True,
    }
    with patch.object(
        agents_mod,
        "fetchrow",
        new_callable=AsyncMock,
        return_value=fake_existing,
    ), patch.object(agents_mod, "execute", new_callable=AsyncMock):
        response = client.post(
            "/agent/register",
            headers={"X-Node-API-Key": "node-secret"},
            json={"name": "friend-msk"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["registration"] == "existing"
    assert body["probe_node_id"] == 11


# --- /agent/bootstrap: requires a valid token, returns node_api_key ---


@patch("rknmon.api.agent_invites_routes.bootstrap_agent", new_callable=AsyncMock)
def test_bootstrap_returns_node_api_key(mock_bootstrap):
    from rknmon.models.schemas import AgentBootstrapOut

    mock_bootstrap.return_value = (
        AgentBootstrapOut(
            central_api_url="https://mon.example.com",
            node_api_key="rnk_abc",
            agent_name="friend-msk",
            agent_location="msk",
            agent_provider="mts",
            probe_interval_seconds=300,
            modes=["dpi"],
            xray_subscription_urls=[],
            xray_subscription_names=[],
            xray_test_url="https://cp.cloudflare.com/",
            xray_socks_start_port=11001,
            install_docker_compose_url="https://mon.example.com/install-agent.sh",
        ),
        {},
    )
    response = client.post(
        "/agent/bootstrap",
        json={"token": "tok", "name": "friend-msk"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["node_api_key"] == "rnk_abc"
    assert body["agent_name"] == "friend-msk"


@patch("rknmon.api.agent_invites_routes.bootstrap_agent", new_callable=AsyncMock)
def test_bootstrap_invalid_token_returns_403(mock_bootstrap):
    mock_bootstrap.side_effect = PermissionError("Invalid, expired, or fully used invite token")
    response = client.post(
        "/agent/bootstrap",
        json={"token": "bad", "name": "friend-msk"},
    )
    assert response.status_code == 403
    assert "Invalid" in response.json()["detail"]


# --- /agent/register: invite-based registration happy path ---


@patch("rknmon.api.agent_invites.bootstrap_agent", new_callable=AsyncMock)
def test_register_with_invite_consumes_token(mock_bootstrap):
    from rknmon.models.schemas import AgentBootstrapOut

    # No existing node for this key:
    with patch(
        "rknmon.api.agents.fetchrow",
        new_callable=AsyncMock,
        return_value=None,
    ), patch(
        "rknmon.api.agents.execute", new_callable=AsyncMock
    ):
        mock_bootstrap.return_value = (
            AgentBootstrapOut(
                central_api_url="https://mon.example.com",
                node_api_key="rnk_xyz",
                agent_name="friend-msk",
                agent_location="msk",
                agent_provider="mts",
                probe_interval_seconds=300,
                modes=["dpi"],
                xray_subscription_urls=[],
                xray_subscription_names=[],
                xray_test_url="https://cp.cloudflare.com/",
                xray_socks_start_port=11001,
                install_docker_compose_url="https://mon.example.com/install-agent.sh",
            ),
            {},
        )
        response = client.post(
            "/agent/register",
            headers={"X-Node-API-Key": "absent-key"},
            json={"name": "friend-msk", "bootstrap_token": "tok"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["registration"] == "bootstrap_pending"
    assert body["bootstrap"]["node_api_key"] == "rnk_xyz"
