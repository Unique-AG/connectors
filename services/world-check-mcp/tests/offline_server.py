# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-22T06:27:45+00:00

"""The server with fakes in place of the upstream and the stores. The tests build it, and so
does `uv run poe architecture`, which lists its tools.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
import httpx2
from key_value.aio.stores.memory import MemoryStore
from mcp_configs import RetrySettings
from pydantic import AnyHttpUrl
from pydantic import SecretStr

from world_check_mcp.mcp import create_server
from world_check_mcp.persistence import Persistence
from world_check_mcp.upstream import UpstreamSettings


def fake_upstream_settings() -> UpstreamSettings:
    """Every field given, so neither the environment nor `.env` changes what the tests see.
    Retries never wait.
    """
    return UpstreamSettings(
        api_key=SecretStr("dummy-api-key"),
        api_secret=SecretStr("dummy-api-secret"),
        api_url=AnyHttpUrl("https://api.example.com"),
        token_url=AnyHttpUrl("https://api.example.com/auth/oauth2/v1/token"),
        timeout_seconds=30,
        retry=RetrySettings(max_attempts=3, max_wait_seconds=0, statuses=frozenset({429, 503})),
    )


def unanswered_upstream() -> httpx2.MockTransport:
    return httpx2.MockTransport(lambda _request: httpx2.Response(404))


@asynccontextmanager
async def open_fake_persistence() -> AsyncGenerator[Persistence]:
    """An in-memory store in place of Redis, which CI does not run."""
    yield Persistence(store=MemoryStore())


def build_server(
    upstream_settings: UpstreamSettings,
    persistence: Persistence,
    upstream_transport: httpx2.MockTransport,
) -> FastMCP:
    """Every client of the server shares `persistence`, as the server's clients share the real
    stores.
    """

    @asynccontextmanager
    async def open_persistence() -> AsyncGenerator[Persistence]:
        yield persistence

    return create_server(upstream_settings, open_persistence, upstream_transport)


@asynccontextmanager
async def offline_server() -> AsyncGenerator[FastMCP]:
    async with open_fake_persistence() as persistence:
        yield build_server(fake_upstream_settings(), persistence, unanswered_upstream())
