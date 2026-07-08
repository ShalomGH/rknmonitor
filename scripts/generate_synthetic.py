#!/usr/bin/env python3
"""
Synthetic target generator for rknmon load testing.
Inserts N random targets into the database.
"""
import asyncio
import random
import string
import sys

from rknmon.db import close_pool, get_pool

DOMAINS = [
    "example.com", "test.org", "demo.net", "site.io", "page.dev",
    "webapp.co", "service.ru", "portal.uk", "cloud.fr", "app.de",
]
CATEGORIES = ["news", "social", "streaming", "messaging", "filehost", "vpn"]


def random_domain():
    prefix = "".join(random.choices(string.ascii_lowercase, k=random.randint(4, 12)))
    suffix = random.choice(DOMAINS)
    return f"{prefix}.{suffix}"


def random_ip():
    return f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}"


async def generate_targets(n: int = 100):
    await get_pool()
    for i in range(n):
        domain = random_domain()
        url = f"https://{domain}/"
        ip = random_ip() if random.random() > 0.3 else None
        category = random.choice(CATEGORIES) if random.random() > 0.2 else None
        state = random.choices(["clear", "suspected", "blocked"], weights=[70, 20, 10])[0]
        await get_pool().execute(
            """
            INSERT INTO targets (url, domain, ip, category, source, is_active, state)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (domain) DO UPDATE SET
                url = EXCLUDED.url,
                ip = COALESCE(EXCLUDED.ip, targets.ip),
                category = COALESCE(EXCLUDED.category, targets.category),
                state = EXCLUDED.state,
                updated_at = now()
            """,
            url, domain, ip, category, "synthetic", True, state,
        )
    print(f"Inserted/updated {n} synthetic targets.")
    await close_pool()


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    asyncio.run(generate_targets(n))
