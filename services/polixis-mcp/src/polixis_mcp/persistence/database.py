# mcp-scaffold-commit: 021f4d5172a8, timestamp: 2026-11-18T11:06:06+00:00

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from mcp_configs import PostgresSettings
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine

# The connection every MCP shares: DATABASE_URL or DB_*, with the chart's TLS settings.
DatabaseSettings = PostgresSettings
# `Persistence.database`: `async with persistence.database() as session:` opens one session.
Database = async_sessionmaker[AsyncSession]


def create_database(settings: DatabaseSettings) -> Database:
    """Connects on first use, so it can exist before the server lifespan opens it: the upstream
    client caches Polixis's answers in it.
    """
    engine = create_async_engine(
        settings.connection_url,
        connect_args=dict(settings.connect_args),
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_pre_ping=True,
    )
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def open_database(database: Database) -> AsyncGenerator[None]:
    """Connects now, so a database the server cannot reach stops it from starting, and closes
    every connection on exit.
    """
    async with database() as session:
        await session.connection()
        engine = session.bind
    assert isinstance(engine, AsyncEngine), "a Database is bound to an engine"
    try:
        yield
    finally:
        await engine.dispose()
