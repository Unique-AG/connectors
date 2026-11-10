# mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00

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

from polixis_mcp.mcp import create_server
from polixis_mcp.persistence import Persistence
from polixis_mcp.upstream import UpstreamSettings


def fake_upstream_settings() -> UpstreamSettings:
    """Every field given, so neither the environment nor `.env` changes what the tests see.
    Retries never wait.
    """
    return UpstreamSettings(
        client_id=SecretStr("dummy-client-id"),
        client_secret=SecretStr("dummy-client-secret"),
        api_key=SecretStr("dummy-api-key"),
        api_url=AnyHttpUrl("https://api.example.com"),
        token_url=AnyHttpUrl("https://auth.example.com/token"),
        timeout_seconds=30,
        retry=RetrySettings(max_attempts=3, max_wait_seconds=0, statuses=frozenset({429, 503})),
    )


def unanswered_upstream() -> httpx2.MockTransport:
    return httpx2.MockTransport(lambda _request: httpx2.Response(404))


class FakeStore(MemoryStore):
    """`MemoryStore` drops an entry past its TTL when it is read, so a cull only counts."""

    culls: int = 0

    async def cull(self) -> None:
        self.culls += 1


@asynccontextmanager
async def open_fake_persistence() -> AsyncGenerator[Persistence]:
    """An in-memory store in place of Postgres, which CI does not run."""
    yield Persistence(store=FakeStore())


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
