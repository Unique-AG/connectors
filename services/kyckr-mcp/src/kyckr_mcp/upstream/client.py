# mcp-scaffold-commit: 6474bb8667dc, timestamp: 2026-11-16T10:36:30+00:00

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

import httpx2
from mcp_openapi.headers import only_headers
from mcp_openapi.retry import RetryAfterPolicy
from mcp_openapi.upstream import OperationClient
import yaml

from kyckr_mcp.upstream.settings import UpstreamSettings

# The name the contexts and tools import the client by, kept the same in every MCP whatever
# the client is. It is an alias, not an abstraction: its API is the client's own.
Upstream = OperationClient

_FORWARDED_HEADERS = frozenset({"accept", "accept-encoding", "connection", "user-agent"})

SPEC = cast(
    dict[str, object],
    yaml.safe_load((Path(__file__).parent / "openapi.yml").read_text()),
)


def upstream_http(
    settings: UpstreamSettings, transport: httpx2.AsyncBaseTransport | None = None
) -> httpx2.AsyncClient:
    """Every request to the upstream goes through it.

    Only the allow-listed headers reach Kyckr, and the key is set on requests to its origin only.
    """
    base_url = str(settings.api_url).rstrip("/")
    authorization = {"Authorization": f"Bearer {settings.api_key.get_secret_value()}"}
    return httpx2.AsyncClient(
        base_url=base_url,
        timeout=settings.timeout_seconds,
        transport=transport,
        headers={"Accept": "application/json"},
        event_hooks={
            "request": [only_headers(_FORWARDED_HEADERS, authorization, origin=base_url)],
        },
    )


@asynccontextmanager
async def open_upstream(
    http: httpx2.AsyncClient, settings: UpstreamSettings
) -> AsyncGenerator[Upstream]:
    """Open the client the contexts receive, over `http`.

    Leaves `http` open: it lives as long as the server, and an httpx client never reopens,
    while every in-memory client enters the lifespan again.
    """
    retry = settings.retry
    policy = RetryAfterPolicy(
        max_attempts=retry.max_attempts,
        max_wait_seconds=retry.max_wait_seconds,
        statuses=retry.statuses,
    )
    yield Upstream(SPEC, http, retry_policy=policy)
