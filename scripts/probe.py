#!/usr/bin/env python3
"""CLI: manual probe run for testing."""
import argparse
import asyncio
import json
import sys
sys.path.insert(0, "src")

from rknmon.probes.http_probe import probe_http
from rknmon.probes.dns_probe import probe_dns
from rknmon.probes.classifier import classify

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("domain", help="Domain to probe")
    parser.add_argument("--url", default=None, help="Full URL (default: https://domain)")
    args = parser.parse_args()

    url = args.url or f"https://{args.domain}"
    print(f"Probing {url} ...")
    http = await probe_http(url)
    print(f"HTTP: status={http.get('status_code')} time={http.get('response_time_ms')}ms error={http.get('error')}")

    dns = await probe_dns(args.domain)
    print(f"DNS: tampered={dns.get('tampered')} nxdomain={dns.get('nxdomain')}")
    for r in dns.get("results", []):
        print(f"  {r['resolver']}: {', '.join(r['ips']) if r['ips'] else r.get('error')}")

    state, details = classify(http, dns)
    print(f"STATE: {state} | details={json.dumps(details)}")

if __name__ == "__main__":
    asyncio.run(main())
