from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from with_intelligence_mcp.config import DatabaseConfig


def create_engine(config: DatabaseConfig) -> AsyncEngine:
    return create_async_engine(
        config.connection_url,
        connect_args=config.connect_args,
        echo=False,
        pool_size=5,
        max_overflow=10,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def read_session(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Reads only, never commits. Use `transaction()` for anything that writes."""
    async with factory() as session:
        yield session


@asynccontextmanager
async def transaction(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Committed on clean exit; `async with` rolls back on error."""
    async with factory() as session:
        yield session
        await session.commit()
