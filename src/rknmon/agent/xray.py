from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import aiohttp


@dataclass(frozen=True)
class XrayProfile:
    name: str
    protocol: str
    host: str
    port: int
    raw_url: str
    subscription_name: str = "default"
    transport: str | None = None
    security: str | None = None
    sni: str | None = None
    fingerprint: str | None = None
    user_id: str | None = None
    params: dict[str, str] = field(default_factory=dict)

    @property
    def stable_id(self) -> str:
        slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", self.name).strip("-")
        return slug or f"{self.protocol}-{self.host}-{self.port}"


def _b64decode_maybe(value: str) -> str | None:
    text = value.strip()
    if not text:
        return None
    padding = "=" * (-len(text) % 4)
    try:
        decoded = base64.urlsafe_b64decode((text + padding).encode()).decode("utf-8")
    except Exception:
        try:
            decoded = base64.b64decode((text + padding).encode()).decode("utf-8")
        except Exception:
            return None
    if any(scheme in decoded for scheme in ("vless://", "vmess://", "trojan://", "ss://")):
        return decoded
    return None


def _subscription_lines(text: str) -> list[str]:
    decoded = _b64decode_maybe(text)
    body = decoded if decoded is not None else text
    return [line.strip() for line in body.replace("\r", "\n").split("\n") if line.strip()]


def parse_subscription_text(text: str, subscription_name: str = "default") -> list[XrayProfile]:
    profiles: list[XrayProfile] = []
    for line in _subscription_lines(text):
        if line.startswith("vmess://"):
            profile = _parse_vmess(line)
        elif line.startswith(("vless://", "trojan://", "ss://")):
            profile = _parse_standard_link(line)
        else:
            profile = None
        if profile is not None:
            profiles.append(_with_subscription(profile, subscription_name))
    return profiles


def _with_subscription(profile: XrayProfile, subscription_name: str) -> XrayProfile:
    return XrayProfile(
        name=profile.name,
        protocol=profile.protocol,
        host=profile.host,
        port=profile.port,
        raw_url=profile.raw_url,
        subscription_name=subscription_name,
        transport=profile.transport,
        security=profile.security,
        sni=profile.sni,
        fingerprint=profile.fingerprint,
        user_id=profile.user_id,
        params=profile.params,
    )


def _parse_vmess(raw_url: str) -> XrayProfile | None:
    payload = raw_url[len("vmess://") :]
    padding = "=" * (-len(payload) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode((payload + padding).encode()).decode("utf-8"))
    except Exception:
        return None
    host = str(data.get("add") or "")
    if not host:
        return None
    return XrayProfile(
        name=str(data.get("ps") or f"vmess-{host}"),
        protocol="vmess",
        host=host,
        port=int(data.get("port") or 443),
        raw_url=raw_url,
        transport=str(data.get("net") or "tcp"),
        security=str(data.get("tls") or "none"),
        sni=str(data.get("sni") or data.get("host") or "") or None,
        fingerprint=str(data.get("fp") or "") or None,
        user_id=str(data.get("id") or "") or None,
        params={k: str(v) for k, v in data.items()},
    )


def _parse_standard_link(raw_url: str) -> XrayProfile | None:
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"vless", "trojan", "ss"} or not parsed.hostname:
        return None
    query = {k: v[0] for k, v in parse_qs(parsed.query).items() if v}
    name = unquote(parsed.fragment) if parsed.fragment else f"{parsed.scheme}-{parsed.hostname}"
    return XrayProfile(
        name=name,
        protocol=parsed.scheme,
        host=parsed.hostname,
        port=int(parsed.port or 443),
        raw_url=raw_url,
        transport=query.get("type") or query.get("transport") or "tcp",
        security=query.get("security") or query.get("tls"),
        sni=query.get("sni") or query.get("peer") or query.get("host"),
        fingerprint=query.get("fp") or query.get("fingerprint"),
        user_id=unquote(parsed.username or "") or None,
        params=query,
    )


async def load_profiles_from_urls(
    subscription_urls: list[str], subscription_names: list[str] | None = None
) -> list[XrayProfile]:
    profiles: list[XrayProfile] = []
    timeout = aiohttp.ClientTimeout(total=30)
    names = subscription_names or []
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for idx, url in enumerate(subscription_urls):
            subscription_name = names[idx] if idx < len(names) and names[idx] else f"sub-{idx + 1}"
            async with session.get(url) as resp:
                resp.raise_for_status()
                profiles.extend(parse_subscription_text(await resp.text(), subscription_name=subscription_name))
    return profiles


def _stream_settings(profile: XrayProfile) -> dict[str, Any]:
    network = profile.transport or "tcp"
    security = profile.security or "none"
    stream: dict[str, Any] = {"network": network, "security": security}
    if security == "reality":
        reality: dict[str, Any] = {}
        if profile.sni:
            reality["serverName"] = profile.sni
        if profile.fingerprint:
            reality["fingerprint"] = profile.fingerprint
        if profile.params.get("pbk"):
            reality["publicKey"] = profile.params["pbk"]
        if profile.params.get("sid"):
            reality["shortId"] = profile.params["sid"]
        if profile.params.get("spx"):
            reality["spiderX"] = profile.params["spx"]
        stream["realitySettings"] = reality
    elif security == "tls":
        tls: dict[str, Any] = {}
        if profile.sni:
            tls["serverName"] = profile.sni
        if profile.fingerprint:
            tls["fingerprint"] = profile.fingerprint
        stream["tlsSettings"] = tls

    if network == "grpc":
        stream["grpcSettings"] = {
            "serviceName": profile.params.get("serviceName") or profile.params.get("serviceName_") or "",
            "multiMode": profile.params.get("mode") == "multi",
        }
    elif network in {"ws", "websocket"}:
        stream["wsSettings"] = {
            "path": profile.params.get("path") or "/",
            "headers": {"Host": profile.params.get("host") or profile.sni or profile.host},
        }
    elif network == "xhttp":
        stream["xhttpSettings"] = {
            "path": profile.params.get("path") or "/",
            "host": profile.params.get("host") or profile.sni or profile.host,
            "mode": profile.params.get("mode") or "auto",
        }
    return stream


def _outbound_for_profile(profile: XrayProfile, tag: str) -> dict[str, Any]:
    if profile.protocol == "vless":
        user: dict[str, Any] = {
            "id": profile.user_id or "",
            "encryption": profile.params.get("encryption") or "none",
        }
        if profile.params.get("flow"):
            user["flow"] = profile.params["flow"]
        return {
            "tag": tag,
            "protocol": "vless",
            "settings": {
                "vnext": [
                    {
                        "address": profile.host,
                        "port": profile.port,
                        "users": [user],
                    }
                ]
            },
            "streamSettings": _stream_settings(profile),
        }
    return {"tag": tag, "protocol": profile.protocol, "raw_url": profile.raw_url}


def build_xray_config(
    profiles: list[XrayProfile], socks_start_port: int = 11001
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    inbounds: list[dict[str, Any]] = []
    outbounds: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []

    seen_ids: dict[str, int] = {}

    for idx, profile in enumerate(profiles):
        port = socks_start_port + idx
        base_id = profile.stable_id
        seen_ids[base_id] = seen_ids.get(base_id, 0) + 1
        safe_id = base_id if seen_ids[base_id] == 1 else f"{base_id}-{seen_ids[base_id]}"
        inbound_tag = f"in-{safe_id}"
        outbound_tag = f"out-{safe_id}"
        inbounds.append(
            {
                "tag": inbound_tag,
                "listen": "127.0.0.1",
                "port": port,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True},
            }
        )
        outbounds.append(_outbound_for_profile(profile, outbound_tag))
        rules.append({"type": "field", "inboundTag": [inbound_tag], "outboundTag": outbound_tag})
        assignments.append(
            {
                "profile_id": safe_id,
                "profile_name": profile.name,
                "subscription_name": profile.subscription_name,
                "protocol": profile.protocol,
                "transport": profile.transport,
                "security": profile.security,
                "sni": profile.sni,
                "fingerprint": profile.fingerprint,
                "host": profile.host,
                "port": profile.port,
                "socks_port": port,
            }
        )

    return {
        "log": {"loglevel": "warning"},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": {"rules": rules},
    }, assignments
