from datetime import datetime
from typing import Literal, Optional

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
    details: Optional[dict] = None


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
    role: Literal["subject", "control", "external"] = "subject"
    agent_version: Optional[str] = None
    public_ip: Optional[str] = None
    bootstrap_token: Optional[str] = None
    bootstrap_nonce: Optional[str] = None


class AgentBootstrapIn(BaseModel):
    token: str
    name: str
    location: Optional[str] = None
    provider: Optional[str] = None
    public_ip: Optional[str] = None
    agent_version: Optional[str] = None
    nonce: Optional[str] = None
    ssh_public_key: Optional[str] = None


class AgentBootstrapOut(BaseModel):
    central_api_url: str
    node_api_key: str
    agent_name: str
    agent_location: Optional[str] = None
    agent_provider: Optional[str] = None
    probe_interval_seconds: int
    modes: list[str]
    xray_subscription_urls: list[str]
    xray_subscription_names: list[str]
    xray_test_url: str
    xray_socks_start_port: int
    install_docker_compose_url: str


class AgentInviteCreateIn(BaseModel):
    name: str
    location: Optional[str] = None
    provider: Optional[str] = None
    modes: list[str] = ["dpi"]
    xray_subscription_urls: list[str] = []
    xray_subscription_names: list[str] = []
    xray_test_url: Optional[str] = "https://cp.cloudflare.com/"
    expires_in_hours: int = 168
    max_uses: int = 1
    note: Optional[str] = None
    created_by: Optional[str] = None


class AgentInviteOut(BaseModel):
    id: int
    token: str
    name: str
    location: Optional[str] = None
    provider: Optional[str] = None
    modes: list[str]
    xray_subscription_urls: list[str]
    xray_subscription_names: list[str]
    xray_test_url: Optional[str] = None
    expires_at: datetime
    max_uses: int
    uses: int
    note: Optional[str] = None
    created_by: Optional[str] = None
    created_at: datetime


class AgentHeartbeatIn(BaseModel):
    agent_version: Optional[str] = None
    public_ip: Optional[str] = None


class SubscriptionHealthIn(BaseModel):
    subscription_name: str
    subscription_url: str
    ok: bool
    http_status: Optional[int] = None
    error_type: Optional[str] = None
    error: Optional[str] = None
    profiles_count: int = 0


class SubscriptionHealthBatchIn(BaseModel):
    items: list[SubscriptionHealthIn]


class Event(BaseModel):
    id: Optional[int] = None
    target_id: int
    event_type: Literal["target_blocked", "target_unblocked", "probe_failed", "state_changed"]
    old_state: Optional[str] = None
    new_state: Optional[str] = None
    details: Optional[dict] = None
    created_at: Optional[datetime] = None
