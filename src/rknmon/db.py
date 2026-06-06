from __future__ import annotations
import asyncpg
from rknmon.config.settings import settings as _s

_pool: asyncpg.Pool | None = None

async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            _s.database_url,
            min_size=_s.pool_min_size,
            max_size=_s.pool_max_size,
            command_timeout=10,
        )
    return _pool

async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None

async def fetchrow(query: str, *args):
    pool = await get_pool()
    return await pool.fetchrow(query, *args)

async def fetch(query: str, *args):
    pool = await get_pool()
    return await pool.fetch(query, *args)

async def execute(query: str, *args):
    pool = await get_pool()
    return await pool.execute(query, *args)
