"""Central-side admin CLI.

Run from a host that has network access to the central FastAPI service
and is allowed to talk to it (admin IP whitelist in nginx). The CLI
exchanges the central `X-API-Key` for invite tokens and pretty-prints
the bootstrap command the friend has to run on their machine.

Examples (Makefile or direct):

    rknmon-admin agent-invite --name friend-msk --location moscow --provider mts

    rknmon-admin agent-invite --name friend-spb \\
        --location spb --provider rostelecom \\
        --modes dpi,xray \\
        --xray-sub "https://sub.example/abcdef,https://sub.example/zyxwvu" \\
        --xray-name "sub-one,sub-two"

    rknmon-admin agent-list-invites
    rknmon-admin agent-revoke-invite 7
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from typing import Any

import aiohttp


def _central_base_url() -> str:
    base = (
        os.getenv("RKNMON_CENTRAL_URL")
        or os.getenv("CENTRAL_API_URL")
        or "https://monitor.example.com"
    )
    return base.rstrip("/")


def _admin_api_key() -> str:
    key = os.getenv("RKNMON_ADMIN_API_KEY") or os.getenv("API_KEY")
    if not key:
        sys.exit(
            "ERROR: set RKNMON_ADMIN_API_KEY (or API_KEY) in the environment; "
            "this CLI uses the central admin X-API-Key."
        )
    return key


def _public_install_url() -> str:
    base = _central_base_url()
    return f"{base}/install-agent.sh"


def _bootstrap_command(token: str, central: str) -> str:
    return (
        f'curl -fsSL {_public_install_url()!r} | sudo bash -s -- \\\n'
        f"    --central {_central_base_url()!r} \\\n"
        f"    --token {token!r}"
    )


def _format_invite(invite: dict[str, Any], central: str) -> str:
    token = invite["token"]
    name = invite.get("name", "?")
    location = invite.get("location") or "—"
    provider = invite.get("provider") or "—"
    modes = ",".join(invite.get("modes") or [])
    expires = invite.get("expires_at", "")
    lines = [
        "  invite_id     : " + str(invite.get("id", "?")),
        "  name          : " + str(name),
        "  location      : " + str(location),
        "  provider      : " + str(provider),
        "  modes         : " + str(modes),
        "  expires_at    : " + str(expires),
        "  uses/max      : "
        + f"{invite.get('uses', 0)}/{invite.get('max_uses', 0)}",
        "  token         : " + token,
    ]
    if invite.get("xray_subscription_urls"):
        lines.append(
            "  xray subs     : "
            + " | ".join(invite.get("xray_subscription_names") or [])
        )
    lines += [
        "",
        "  Run on friend's machine:",
        "",
        _bootstrap_command(token, central),
    ]
    return "\n".join(lines)


async def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = _central_base_url() + path
    headers = {"X-API-Key": _admin_api_key(), "Content-Type": "application/json"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(url, json=payload) as resp:
            body = await resp.text()
            if resp.status >= 400:
                sys.exit(
                    f"ERROR: {resp.status} from {url}\n{body}"
                )
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                sys.exit(f"ERROR: invalid JSON from {url}\n{body}")


async def _get_json(path: str) -> Any:
    url = _central_base_url() + path
    headers = {"X-API-Key": _admin_api_key()}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, headers=headers) as resp:
            body = await resp.text()
            if resp.status >= 400:
                sys.exit(
                    f"ERROR: {resp.status} from {url}\n{body}"
                )
            return json.loads(body)


async def _delete(path: str) -> Any:
    url = _central_base_url() + path
    headers = {"X-API-Key": _admin_api_key()}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.delete(url, headers=headers) as resp:
            body = await resp.text()
            if resp.status >= 400:
                sys.exit(
                    f"ERROR: {resp.status} from {url}\n{body}"
                )
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return body


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rknmon-admin")
    sub = p.add_subparsers(dest="cmd", required=True)

    invite = sub.add_parser("agent-invite", help="Mint a single-use agent install invite")
    invite.add_argument("--name", required=True, help="Probe node name (e.g. friend-msk)")
    invite.add_argument("--location", help="City / region label, free text")
    invite.add_argument("--provider", help="ISP label, free text")
    invite.add_argument(
        "--modes",
        default="dpi",
        help="Comma-separated modes: dpi, xray, dpi,xray (default: dpi)",
    )
    invite.add_argument(
        "--xray-sub",
        default="",
        help="Comma-separated Xray subscription URLs (only for xray mode)",
    )
    invite.add_argument(
        "--xray-name",
        default="",
        help="Comma-separated safe display names matching --xray-sub",
    )
    invite.add_argument(
        "--xray-test-url",
        default="https://cp.cloudflare.com/",
    )
    invite.add_argument(
        "--expires-in-hours",
        type=int,
        default=168,
        help="Invite TTL in hours (default 168 = 7 days)",
    )
    invite.add_argument(
        "--max-uses",
        type=int,
        default=1,
        help="How many times the invite can be redeemed (default 1)",
    )
    invite.add_argument("--note", help="Free-text note stored on the invite row")
    invite.add_argument(
        "--created-by",
        default=os.getenv("USER", "admin"),
        help="Who is creating the invite (stored on the row)",
    )

    sub.add_parser("agent-list-invites", help="List active invites")
    sub.add_parser(
        "agent-list-invites-all", help="List all invites (including used/expired)"
    )

    revoke = sub.add_parser("agent-revoke-invite", help="Revoke an unused invite")
    revoke.add_argument("invite_id", type=int)

    return p


def _split_csv(value: str) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


async def main_async(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    central = _central_base_url()

    if args.cmd == "agent-invite":
        payload = {
            "name": args.name,
            "location": args.location,
            "provider": args.provider,
            "modes": _split_csv(args.modes) or ["dpi"],
            "xray_subscription_urls": _split_csv(args.xray_sub),
            "xray_subscription_names": _split_csv(args.xray_name),
            "xray_test_url": args.xray_test_url,
            "expires_in_hours": args.expires_in_hours,
            "max_uses": args.max_uses,
            "note": args.note,
            "created_by": args.created_by,
        }
        invite = await _post_json("/admin/agents/invites", payload)
        print("Invite created:")
        print(_format_invite(invite, central))

    elif args.cmd == "agent-list-invites":
        invites = await _get_json("/admin/agents/invites")
        for inv in invites:
            print(_format_invite(inv, central))
            print("-" * 60)

    elif args.cmd == "agent-list-invites-all":
        invites = await _get_json("/admin/agents/invites?include_inactive=true")
        for inv in invites:
            print(_format_invite(inv, central))
            print("-" * 60)

    elif args.cmd == "agent-revoke-invite":
        res = await _delete(f"/admin/agents/invites/{args.invite_id}")
        print(res)

    else:  # pragma: no cover
        build_parser().print_help()
        sys.exit(1)


def main() -> None:
    import asyncio

    asyncio.run(main_async())


if __name__ == "__main__":
    main()
