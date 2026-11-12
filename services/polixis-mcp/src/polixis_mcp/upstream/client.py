# mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from datetime import timedelta
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

from polixis_mcp.upstream.quota import QuotaAwareRetryPolicy
from polixis_mcp.upstream.quota import QuotaGate
from polixis_mcp.upstream.recording import CassetteTransport
from polixis_mcp.upstream.recording import RecordingMode
from polixis_mcp.upstream.recording import token_transport
from polixis_mcp.upstream.rejections import reject_error_body
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
    """Every request to the upstream goes through it, from `Upstream` and the generated tools,
    so its connection limit caps the requests in flight and its quota gate stops them all once
    Polixis says the quota is spent. `limits` applies to the default transport only, not to one
    a test passes.

    `now` is the clock the client-credentials token's expiry and the quota cooldown are read
    against.

    With `UPSTREAM_RECORDING_MODE` set, and no `transport` given, requests go through a
    `CassetteTransport`, which saves Polixis's answers or replays them.
    """
    clock = now or _utc_now
    limits = httpx2.Limits(max_connections=settings.max_concurrent_requests)
    api_transport, auth_transport = transport, transport
    if transport is None and settings.recording.mode is not RecordingMode.OFF:
        api_transport = CassetteTransport(
            settings.recording, httpx2.AsyncHTTPTransport(limits=limits)
        )
        auth_transport = token_transport(settings.recording)
    quota = QuotaGate(cooldown=timedelta(seconds=settings.quota_cooldown_seconds), now=clock)
    return httpx2.AsyncClient(
        base_url=str(settings.api_url).rstrip("/"),
        timeout=settings.timeout_seconds,
        limits=limits,
        event_hooks={"request": [quota.refuse_while_spent], "response": [quota.record]},
        transport=api_transport,
        auth=ClientCredentialsAuth(
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            api_key=settings.api_key,
            token_url=str(settings.token_url),
            timeout=settings.timeout_seconds,
            transport=auth_transport,
            now=clock,
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
    policy = QuotaAwareRetryPolicy(
        retry_after=RetryAfterPolicy(
            max_attempts=retry.max_attempts,
            max_wait_seconds=retry.max_wait_seconds,
            statuses=retry.statuses,
        )
    )
    yield Upstream(SPEC, http, retry_policy=policy, response_check=reject_error_body)


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
