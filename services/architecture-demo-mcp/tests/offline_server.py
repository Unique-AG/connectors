# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-21T12:09:32+00:00

"""The server with fakes in place of the upstream and the stores. The tests build it, and so
does `uv run poe architecture`, which lists its tools.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider
import httpx2
from key_value.aio.stores.memory import MemoryStore
from mcp_configs import RetrySettings
from pydantic import AnyHttpUrl
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from architecture_demo_mcp.mcp import create_server
from architecture_demo_mcp.persistence import Base
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import UpstreamSettings


def fake_upstream_settings() -> UpstreamSettings:
    """Every field given, so neither the environment nor `.env` changes what the tests see.
    Retries never wait.
    """
    return UpstreamSettings(
        api_key=SecretStr("dummy-api-key"),
        api_url=AnyHttpUrl("https://api.tiingo.com"),
        timeout_seconds=30,
        retry=RetrySettings(max_attempts=3, max_wait_seconds=0, statuses=frozenset({429, 503})),
    )


def unanswered_upstream() -> httpx2.MockTransport:
    return httpx2.MockTransport(lambda _request: httpx2.Response(404))


@asynccontextmanager
async def open_fake_persistence() -> AsyncGenerator[Persistence]:
    """SQLite and an in-memory store in place of Postgres and Redis, which CI does not run."""
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield Persistence(
        database=async_sessionmaker(engine, expire_on_commit=False), store=MemoryStore()
    )
    await engine.dispose()


def build_server(
    upstream_settings: UpstreamSettings,
    persistence: Persistence,
    upstream_transport: httpx2.MockTransport,
    *,
    auth: AuthProvider | None = None,
) -> FastMCP:
    """Every client of the server shares `persistence`, as the server's clients share the real
    stores.
    """

    @asynccontextmanager
    async def open_persistence() -> AsyncGenerator[Persistence]:
        yield persistence

    return create_server(upstream_settings, open_persistence, upstream_transport, auth=auth)


@asynccontextmanager
async def offline_server() -> AsyncGenerator[FastMCP]:
    async with open_fake_persistence() as persistence:
        yield build_server(fake_upstream_settings(), persistence, unanswered_upstream())
