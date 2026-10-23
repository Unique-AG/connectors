# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-21T12:09:32+00:00

import asyncio

from alembic import context
from mcp_configs import PostgresSettings
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from architecture_demo_mcp.persistence.models import Base

assert not context.is_offline_mode(), "migrations run against a live database only"
settings = PostgresSettings()


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


async def migrate() -> None:
    engine = create_async_engine(
        settings.connection_url, connect_args=dict(settings.connect_args), poolclass=pool.NullPool
    )
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


asyncio.run(migrate())
