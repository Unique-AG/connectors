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

from polixis_mcp.shared import ResponseCache
from polixis_mcp.upstream.answers import answer_check
from polixis_mcp.upstream.cache import CachingTransport
from polixis_mcp.upstream.cache import record_cache_read
from polixis_mcp.upstream.quota import AdmissionTransport
from polixis_mcp.upstream.quota import QuotaGate
from polixis_mcp.upstream.rejections import reject_error_body
from polixis_mcp.upstream.routes import EXPOSED
from polixis_mcp.upstream.settings import UpstreamSettings
from polixis_mcp.upstream.token import ClientCredentialsTransport

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
    cache: ResponseCache | None = None,
    now: Callable[[], datetime] | None = None,
) -> httpx2.AsyncClient:
    """Every request to the upstream goes through it, from `Upstream` and the generated tools,
    so its admission caps the requests in flight and its quota gate stops them all once Polixis
    says the quota is spent, the ones waiting for a slot included.

    With `cache` given and on in `settings`, the same request is answered from it within its
    TTL. The cache sits outside the admission and the client credentials, so a cached answer
    neither waits for a slot, nor is refused while the quota is spent, nor fetches a token.

    `now` is the clock the client-credentials token's expiry, the quota cooldown and the cache's
    TTL are read against.
    """
    clock = now or _utc_now
    network = transport or httpx2.AsyncHTTPTransport(
        limits=httpx2.Limits(max_connections=settings.max_concurrent_requests)
    )
    signed = ClientCredentialsTransport(
        network,
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        api_key=settings.api_key,
        token_url=str(settings.token_url),
        timeout=settings.timeout_seconds,
        token_transport=transport,
        now=clock,
    )
    quota = QuotaGate(cooldown=timedelta(seconds=settings.quota_cooldown_seconds), now=clock)
    admission = AdmissionTransport(signed, slots=settings.max_concurrent_requests, quota=quota)
    return httpx2.AsyncClient(
        base_url=str(settings.api_url).rstrip("/"),
        timeout=settings.timeout_seconds,
        event_hooks={"response": [quota.record, record_cache_read]},
        transport=(
            CachingTransport(
                admission,
                cache=cache,
                settings=settings.cache,
                usable=answer_check(SPEC, base_path=httpx2.URL(str(settings.api_url)).path),
                now=clock,
            )
            if cache is not None and settings.cache.enabled
            else admission
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
    policy = (
        RetryAfterPolicy(
            max_attempts=retry.max_attempts,
            max_wait_seconds=retry.max_wait_seconds,
            statuses=retry.statuses,
        )
        if settings.retry_enabled
        else None
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
