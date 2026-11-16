# mcp-scaffold-commit: 6474bb8667dc, timestamp: 2026-11-16T10:36:30+00:00

"""The server with fakes in place of the upstream and the stores. The tests build it, and so
does `uv run poe architecture`, which lists its tools.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider
import httpx2
from mcp_configs import RateLimitSettings
from pydantic import AnyHttpUrl
from pydantic import SecretStr

from kyckr_mcp.mcp import create_server
from kyckr_mcp.persistence import Persistence
from kyckr_mcp.upstream import UpstreamSettings


def fake_upstream_settings() -> UpstreamSettings:
    """Every field given but the retry policy, which keeps the production statuses. Retries
    never wait.
    """
    defaults = UpstreamSettings(
        api_key=SecretStr("dummy-api-key"),
        api_url=AnyHttpUrl("https://test-api.kyckr.com/v2"),
        default_customer_reference=None,
        default_contact_email=None,
        timeout_seconds=30,
    )
    retry = type(defaults.retry).model_construct(max_attempts=3, max_wait_seconds=0)
    return defaults.model_copy(update={"retry": retry})


def unanswered_upstream() -> httpx2.MockTransport:
    return httpx2.MockTransport(lambda _request: httpx2.Response(404))


@asynccontextmanager
async def open_fake_persistence() -> AsyncGenerator[Persistence]:
    yield Persistence()


def build_server(
    upstream_settings: UpstreamSettings,
    persistence: Persistence,
    upstream_transport: httpx2.MockTransport,
    *,
    auth: AuthProvider | None = None,
    rate_limit: RateLimitSettings | None = None,
) -> FastMCP:
    """Every client of the server shares `persistence`, as the server's clients share the real
    stores.
    """

    @asynccontextmanager
    async def open_persistence() -> AsyncGenerator[Persistence]:
        yield persistence

    return create_server(
        upstream_settings, open_persistence, upstream_transport, auth=auth, rate_limit=rate_limit
    )


@asynccontextmanager
async def offline_server() -> AsyncGenerator[FastMCP]:
    async with open_fake_persistence() as persistence:
        yield build_server(fake_upstream_settings(), persistence, unanswered_upstream())
