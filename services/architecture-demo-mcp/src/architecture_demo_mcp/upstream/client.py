from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

from fastmcp.server.providers.openapi import MCPType
from fastmcp.server.providers.openapi import OpenAPIProvider
import httpx2
from mcp_openapi.openapi import mcp_name
from mcp_openapi.openapi import PASSTHROUGH_TAG
from mcp_openapi.openapi import route_map
from mcp_openapi.openapi import set_tool_hints
from mcp_openapi.retry import RetryAfterPolicy
from mcp_openapi.upstream import OperationClient
import yaml

from architecture_demo_mcp.upstream.routes import EXPOSED
from architecture_demo_mcp.upstream.settings import UpstreamSettings

# The name the contexts and tools import the client by, kept the same in every MCP whatever
# the client is. It is an alias, not an abstraction: its API is the client's own.
Upstream = OperationClient

SPEC = cast(
    dict[str, object],
    yaml.safe_load((Path(__file__).parent / "openapi.yml").read_text()),
)


def upstream_http(
    settings: UpstreamSettings, transport: httpx2.AsyncBaseTransport | None = None
) -> httpx2.AsyncClient:
    """Every request to the upstream goes through it, from `Upstream` and the generated tools."""
    return httpx2.AsyncClient(
        base_url=str(settings.api_url).rstrip("/"),
        timeout=settings.timeout_seconds,
        transport=transport,
        headers={
            "Authorization": f"Token {settings.api_key.get_secret_value()}",
            "Accept": "application/json",
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


def upstream_tools(http: httpx2.AsyncClient) -> OpenAPIProvider:
    """The operations in `EXPOSED`, served as tools straight from the spec. Retries do not apply."""
    missing = set(EXPOSED) - Upstream(SPEC, http).operation_ids
    assert not missing, f"operationIds in EXPOSED but not in the spec: {sorted(missing)}"
    return OpenAPIProvider(
        SPEC,
        http,
        route_map_fn=route_map(dict.fromkeys(EXPOSED, MCPType.TOOL)),
        mcp_names={operation_id: mcp_name(operation_id) for operation_id in EXPOSED},
        mcp_component_fn=set_tool_hints,
        tags={PASSTHROUGH_TAG},
    )
