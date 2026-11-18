# mcp-scaffold-commit: 021f4d5172a8, timestamp: 2026-11-18T11:06:06+00:00

from mcp_configs import PostgresSettings
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import create_async_engine

# The connection every MCP shares: DATABASE_URL or DB_*, with the chart's TLS settings.
DatabaseSettings = PostgresSettings


def create_engine(settings: DatabaseSettings) -> AsyncEngine:
    """Connects on first use, so it can exist before the server lifespan opens it."""
    return create_async_engine(
        settings.connection_url,
        connect_args=dict(settings.connect_args),
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_pre_ping=True,
    )
