"""
Async PostgreSQL connection pool using asyncpg.
"""

import asyncpg
import logging
from app.config import settings

logger = logging.getLogger(__name__)

# Global connection pool
_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    """Get or create the connection pool."""
    global _pool
    if _pool is None:
        _pool = await create_pool()
    return _pool


async def create_pool() -> asyncpg.Pool:
    """Create a new connection pool."""
    global _pool
    try:
        _pool = await asyncpg.create_pool(
            dsn=settings.DATABASE_URL,
            min_size=2,
            max_size=10,
            command_timeout=30,
            statement_cache_size=0,  # Required for Neon.tech
        )
        logger.info("Database connection pool created successfully")
        return _pool
    except Exception as e:
        logger.error(f"Failed to create database pool: {e}")
        raise


async def close_pool():
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed")


async def execute(query: str, *args):
    """Execute a query without returning results."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(query, *args)


async def fetch(query: str, *args) -> list:
    """Execute a query and return all rows."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *args)
        return [dict(row) for row in rows]


async def fetchrow(query: str, *args) -> dict | None:
    """Execute a query and return a single row."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, *args)
        return dict(row) if row else None


async def fetchval(query: str, *args):
    """Execute a query and return a single value."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(query, *args)


async def execute_many(query: str, args_list: list):
    """Execute a query with multiple sets of arguments."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(query, args_list)


async def execute_batch(statements: list[tuple[str, list]]):
    """Execute multiple different statements in a transaction."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for query, args in statements:
                await conn.execute(query, *args)


async def init_schema():
    """Initialize database schema from schema.sql."""
    import os
    schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schema.sql")

    if not os.path.exists(schema_path):
        logger.warning(f"Schema file not found: {schema_path}")
        return

    with open(schema_path, "r") as f:
        schema_sql = f.read()

    pool = await get_pool()
    async with pool.acquire() as conn:
        # pg_trgm might not be available, handle gracefully
        try:
            await conn.execute(schema_sql)
            logger.info("Database schema initialized successfully")
        except Exception as e:
            # Try without trigram extension
            logger.warning(f"Schema init with trigram failed, trying without: {e}")
            schema_no_trgm = schema_sql.replace(
                "CREATE EXTENSION IF NOT EXISTS pg_trgm;", ""
            )
            # Remove trigram indexes
            lines = schema_no_trgm.split("\n")
            filtered = [l for l in lines if "gin_trgm_ops" not in l]
            await conn.execute("\n".join(filtered))
            logger.info("Database schema initialized (without trigram)")
