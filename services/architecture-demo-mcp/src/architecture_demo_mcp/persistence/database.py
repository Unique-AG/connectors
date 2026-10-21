from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from mcp_configs import PostgresSettings
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine

# The connection every MCP shares: DATABASE_URL or DB_*, with the chart's TLS settings.
DatabaseSettings = PostgresSettings
# `Persistence.database`: `async with persistence.database() as session:` opens one session.
Database = async_sessionmaker[AsyncSession]


@asynccontextmanager
async def open_database(settings: DatabaseSettings) -> AsyncGenerator[Database]:
    engine = create_async_engine(
        settings.connection_url,
        connect_args=dict(settings.connect_args),
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_pre_ping=True,
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
