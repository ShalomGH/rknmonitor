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

class Event(BaseModel):
    id: Optional[int] = None
    target_id: int
    event_type: Literal["target_blocked", "target_unblocked", "probe_failed", "state_changed"]
    old_state: Optional[str] = None
    new_state: Optional[str] = None
    details: Optional[dict] = None
    created_at: Optional[datetime] = None
