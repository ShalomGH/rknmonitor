#!/usr/bin/env python3
"""CLI: run evaluation + state transitions manually."""
import asyncio
import sys
sys.path.insert(0, "src")

from rknmon.db import get_pool, close_pool
from rknmon.db_schema import init_schema
from rknmon.probes.evaluator import evaluate_targets

async def main():
    await get_pool()
    await init_schema()
    events = await evaluate_targets()
    print(f"Emitted {len(events)} events")
    for e in events:
        print(f"  target={e['target_id']}: {e['old_state']} -> {e['new_state']} ({e['event_type']})")
    await close_pool()

if __name__ == "__main__":
    asyncio.run(main())
