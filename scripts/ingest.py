#!/usr/bin/env python3
"""CLI: ingest targets from CSV."""
import argparse
import asyncio
import sys
sys.path.insert(0, "src")

from rknmon.db import get_pool, close_pool
from rknmon.db_schema import init_schema
from rknmon.ingest.csv_loader import ingest_csv

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", help="Path to CSV file")
    parser.add_argument("--source", default="csv")
    parser.add_argument("--category", default=None)
    args = parser.parse_args()

    await get_pool()
    await init_schema()
    count = await ingest_csv(args.csv, source=args.source, category=args.category)
    print(f"Ingested {count} targets")
    await close_pool()

if __name__ == "__main__":
    asyncio.run(main())
