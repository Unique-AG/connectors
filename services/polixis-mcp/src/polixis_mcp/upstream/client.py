# mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from datetime import UTC
from pathlib import Path
from typing import cast

from fastmcp.server.providers.openapi import MCPType
from fastmcp.server.providers.openapi import OpenAPIProvider
from fastmcp.server.providers.openapi import OpenAPIResource
from fastmcp.server.providers.openapi import OpenAPIResourceTemplate
from fastmcp.server.providers.openapi import OpenAPITool
from fastmcp.utilities.openapi import HTTPRoute
import httpx2
from mcp_openapi.openapi import mcp_name
from mcp_openapi.openapi import route_map
from mcp_openapi.retry import RetryAfterPolicy
from mcp_openapi.upstream import OperationClient
from mcp_types import ToolAnnotations
import yaml

from polixis_mcp.upstream.routes import EXPOSED
from polixis_mcp.upstream.settings import UpstreamSettings
from polixis_mcp.upstream.token import ClientCredentialsAuth

# The name the contexts and tools import the client by, kept the same in every MCP whatever
# the client is. It is an alias, not an abstraction: its API is the client's own.
Upstream = OperationClient

SPEC = cast(
    dict[str, object],
    yaml.safe_load((Path(__file__).parent / "openapi.yml").read_text()),
)


def upstream_http(
    settings: UpstreamSettings,
    transport: httpx2.AsyncBaseTransport | None = None,
    *,
    now: Callable[[], datetime] | None = None,
) -> httpx2.AsyncClient:
    """Every request to the upstream goes through it, from `Upstream` and the generated tools.

    `now` is the clock the client-credentials token's expiry is read against.
    """
    return httpx2.AsyncClient(
        base_url=str(settings.api_url).rstrip("/"),
        timeout=settings.timeout_seconds,
        transport=transport,
        auth=ClientCredentialsAuth(
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            api_key=settings.api_key,
            token_url=str(settings.token_url),
            timeout=settings.timeout_seconds,
            transport=transport,
            now=now or _utc_now,
        ),
        headers={"Accept": "application/json"},
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


def upstream_tools(http: httpx2.AsyncClient) -> OpenAPIProvider:
    """The operations in `EXPOSED`, served as tools straight from the spec. Retries do not apply."""
    missing = set(EXPOSED) - Upstream(SPEC, http).operation_ids
    assert not missing, f"operationIds in EXPOSED but not in the spec: {sorted(missing)}"
    return OpenAPIProvider(
        SPEC,
        http,
        route_map_fn=route_map(dict.fromkeys(EXPOSED, MCPType.TOOL)),
        mcp_names={operation_id: mcp_name(operation_id) for operation_id in EXPOSED},
        mcp_component_fn=_read_only_hints,
    )


def _read_only_hints(
    _route: HTTPRoute, component: OpenAPITool | OpenAPIResource | OpenAPIResourceTemplate
) -> None:
    """Every Polixis operation only reads, the POSTs included: they post a query, not a change."""
    if isinstance(component, OpenAPITool):
        component.annotations = ToolAnnotations(read_only_hint=True, open_world_hint=True)


def _utc_now() -> datetime:
    return datetime.now(UTC)
