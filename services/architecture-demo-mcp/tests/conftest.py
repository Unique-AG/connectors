from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
import httpx2
from key_value.aio.stores.memory import MemoryStore
from mcp_runtime import ServerSettings
from pydantic import SecretStr
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from architecture_demo_mcp.mcp import create_server
from architecture_demo_mcp.persistence import Base
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import UpstreamSettings


@pytest.fixture
def server_settings() -> ServerSettings:
    return ServerSettings(_env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.fixture
def upstream_settings() -> UpstreamSettings:
    return UpstreamSettings(api_key=SecretStr("dummy-api-key"), _env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.fixture
def upstream_transport() -> httpx2.MockTransport:
    """Stands in for the upstream.

    Answer each route with fixed data, as FakeTiingo does in services/architecture-demo-mcp.
    """
    return httpx2.MockTransport(lambda _request: httpx2.Response(404))


@pytest.fixture
async def persistence() -> AsyncGenerator[Persistence]:
    """SQLite and an in-memory store in place of Postgres and Redis, which CI does not run.

    Every client the tests open shares it, as the server's clients share the real stores.
    """
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield Persistence(
        database=async_sessionmaker(engine, expire_on_commit=False), store=MemoryStore()
    )
    await engine.dispose()


@pytest.fixture
def server(
    upstream_settings: UpstreamSettings,
    persistence: Persistence,
    upstream_transport: httpx2.MockTransport,
) -> FastMCP:
    @asynccontextmanager
    async def open_persistence() -> AsyncGenerator[Persistence]:
        yield persistence

    return create_server(upstream_settings, open_persistence, upstream_transport)
