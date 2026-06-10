"""Admin endpoints to mint and revoke single-use agent install invites.

These routes sit OUTSIDE the /agent/* prefix because they require the
central API key, not the node API key. They are not exposed to the
unauthenticated internet — they live behind nginx with `allow` whitelists
and the same `X-API-Key` middleware the rest of the admin API uses.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from rknmon.api.agent_invites import (
    bootstrap_agent,
    create_invite,
    list_invites,
    revoke_invite,
)
from rknmon.config.settings import settings
from rknmon.models.schemas import (
    AgentBootstrapIn,
    AgentBootstrapOut,
    AgentInviteCreateIn,
    AgentInviteOut,
)

router = APIRouter(prefix="/admin/agents", tags=["admin-agents"])


def _require_admin(request: Request) -> None:
    api_key = request.headers.get("X-API-Key")
    if not api_key or api_key != settings.api_key:
        raise HTTPException(
            status_code=403, detail="Forbidden: invalid or missing admin API key"
        )


@router.post("/invites", response_model=AgentInviteOut)
async def post_invite(request: Request, payload: AgentInviteCreateIn):
    _require_admin(request)
    try:
        return await create_invite(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/invites", response_model=list[AgentInviteOut])
async def get_invites(request: Request, include_inactive: bool = False):
    _require_admin(request)
    return await list_invites(active_only=not include_inactive)


@router.delete("/invites/{invite_id}")
async def delete_invite(request: Request, invite_id: int):
    _require_admin(request)
    ok = await revoke_invite(invite_id)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Invite is already used or revoked; cannot delete",
        )
    return {"revoked": True, "id": invite_id}


# Public, no-auth bootstrap: the friend hits this once, the token is
# single-use and bound to the pre-registered name / location / provider.
public_router = APIRouter(prefix="/agent", tags=["agent-bootstrap"])


@public_router.post("/bootstrap", response_model=AgentBootstrapOut)
async def post_bootstrap(payload: AgentBootstrapIn):
    if not payload.token or not payload.name:
        raise HTTPException(status_code=400, detail="token and name are required")
    try:
        out, _invite = await bootstrap_agent(
            token=payload.token,
            name=payload.name,
            location=payload.location,
            provider=payload.provider,
            public_ip=payload.public_ip,
            agent_version=payload.agent_version,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return out
