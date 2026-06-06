import asyncio
import aiodns
from typing import List, Dict

RESOLVERS = [
    ("system", None),
    ("google", "8.8.8.8"),
    ("cloudflare", "1.1.1.1"),
    ("quad9", "9.9.9.9"),
]

async def probe_dns(domain: str, timeout: float = 5.0) -> Dict:
    results = []
    loop = asyncio.get_event_loop()

    async def resolve_with(name: str, resolver_ip: str | None):
        try:
            if resolver_ip:
                resolver = aiodns.DNSResolver(nameservers=[resolver_ip])
            else:
                resolver = aiodns.DNSResolver()
            result = await resolver.query_dns(domain, "A")
            if isinstance(result, list):
                ips = [r.host for r in result]
            else:
                ips = [result.host]
            return {"resolver": name, "ips": ips, "error": None}
        except aiodns.error.DNSError as e:
            return {"resolver": name, "ips": [], "error": f"dns_error_{e.args[0]}"}
        except Exception as e:
            return {"resolver": name, "ips": [], "error": f"{e.__class__.__name__}: {str(e)[:100]}"}

    tasks = [resolve_with(name, ip) for name, ip in RESOLVERS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # unwrap exceptions
    clean = []
    for r in results:
        if isinstance(r, Exception):
            clean.append({"resolver": "unknown", "ips": [], "error": f"exception: {r}"})
        else:
            clean.append(r)

    # compare answers
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
    }
