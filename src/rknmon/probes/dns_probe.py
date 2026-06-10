import asyncio
import socket
import time
from typing import Dict

import aiodns

RESOLVERS = [
    ("system", None),
    ("google", "8.8.8.8"),
    ("cloudflare", "1.1.1.1"),
    ("quad9", "9.9.9.9"),
]


async def probe_dns(domain: str, timeout: float = 5.0) -> Dict:
    async def resolve_with(name: str, resolver_ip: str | None):
        started = time.perf_counter()
        try:
            if resolver_ip:
                resolver = aiodns.DNSResolver(nameservers=[resolver_ip])
            else:
                resolver = aiodns.DNSResolver()

            answer = await asyncio.wait_for(
                resolver.gethostbyname(domain, socket.AF_INET),
                timeout=timeout,
            )
            ips = list(answer.addresses or [])
            elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
            return {
                "resolver": name,
                "ips": ips,
                "error": None,
                "response_time_ms": elapsed_ms,
            }
        except asyncio.TimeoutError:
            return {
                "resolver": name,
                "ips": [],
                "error": "timeout",
                "response_time_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        except aiodns.error.DNSError as e:
            code = e.args[0] if e.args else "unknown"
            return {
                "resolver": name,
                "ips": [],
                "error": f"dns_error_{code}",
                "response_time_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        except Exception as e:
            return {
                "resolver": name,
                "ips": [],
                "error": f"{e.__class__.__name__}: {str(e)[:100]}",
                "response_time_ms": round((time.perf_counter() - started) * 1000, 2),
            }

    gathered = await asyncio.gather(
        *(resolve_with(name, ip) for name, ip in RESOLVERS),
        return_exceptions=True,
    )

    clean = []
    latencies = []
    for item in gathered:
        if isinstance(item, Exception):
            clean.append({"resolver": "unknown", "ips": [], "error": f"exception: {item}", "response_time_ms": None})
            continue
        clean.append(item)
        rt = item.get("response_time_ms")
        if rt is not None:
            latencies.append(rt)

    system_ips = set()
    google_ips = set()
    for c in clean:
        if c["resolver"] == "system":
            system_ips = set(c["ips"])
        elif c["resolver"] == "google":
            google_ips = set(c["ips"])

    tampered = bool(system_ips and google_ips and system_ips != google_ips)

    return {
        "domain": domain,
        "results": clean,
        "tampered": tampered,
        "nxdomain": any("NXDOMAIN" in str(r.get("error", "")) for r in clean),
        "response_time_ms": round(min(latencies), 2) if latencies else None,
    }
