from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, HttpUrl

class Target(BaseModel):
    id: Optional[int] = None
    url: HttpUrl
    domain: str
    ip: Optional[str] = None
    category: Optional[str] = None
    source: str = "manual"
    is_active: bool = True
    state: Optional[Literal["clear", "suspected", "blocked"]] = "clear"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class ProbeResult(BaseModel):
    id: Optional[int] = None
    target_id: int
    probe_type: Literal["http", "https", "dns"]
    status_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    body_hash: Optional[str] = None
    error: Optional[str] = None
    resolver: Optional[str] = None
    result: Optional[dict] = None
    checked_at: Optional[datetime] = None

class AgentProbeIn(BaseModel):
    target_id: int
    probe_type: Literal["http", "https", "dns"]
    status_code: Optional[int] = None
    response_time_ms: Optional[float] = None
    body_hash: Optional[str] = None
    error: Optional[str] = None
    resolver: Optional[str] = None
    result: Optional[dict] = None

class AgentProbeBatchIn(BaseModel):
    results: list[AgentProbeIn]


class XrayProbeIn(BaseModel):
    profile_id: str
    profile_name: str
    subscription_name: str = "default"
    protocol: str
    transport: Optional[str] = None
    security: Optional[str] = None
    sni: Optional[str] = None
    fingerprint: Optional[str] = None
    server_host: str
    server_port: int
    socks_port: Optional[int] = None
    test_url: str
    ok: bool
    latency_ms: Optional[float] = None
    http_status: Optional[int] = None
    bytes_downloaded: Optional[int] = None
    error_type: Optional[str] = None
    error: Optional[str] = None


class XrayProbeBatchIn(BaseModel):
    results: list[XrayProbeIn]


class DpiProbeIn(BaseModel):
    checker: str
    target: str
    method: str
    ok: bool
    latency_ms: Optional[float] = None
    http_status: Optional[int] = None
    error_type: Optional[str] = None
    error: Optional[str] = None
    details: Optional[dict] = None


class DpiProbeBatchIn(BaseModel):
    results: list[DpiProbeIn]


class AgentRegisterIn(BaseModel):
    name: str
    location: Optional[str] = None
    provider: Optional[str] = None
    agent_version: Optional[str] = None
    public_ip: Optional[str] = None


class AgentHeartbeatIn(BaseModel):
    agent_version: Optional[str] = None
    public_ip: Optional[str] = None


class Event(BaseModel):
    id: Optional[int] = None
    target_id: int
    event_type: Literal["target_blocked", "target_unblocked", "probe_failed", "state_changed"]
    old_state: Optional[str] = None
    new_state: Optional[str] = None
    details: Optional[dict] = None
    created_at: Optional[datetime] = None
