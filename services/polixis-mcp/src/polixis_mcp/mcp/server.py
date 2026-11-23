# mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider
from fastmcp.server.providers import FileSystemProvider
import httpx2
from mcp_configs import RateLimitSettings
from mcp_observability import access_token_subject
from mcp_observability import RateLimitMiddleware
from mcp_observability import ToolCallObservabilityMiddleware
from mcp_observability import validate_trace_declarations

from polixis_mcp.mcp.freshness_tracking import FreshnessTracking
from polixis_mcp.mcp.spec_tool_errors import SpecToolErrors
from polixis_mcp.persistence import cull_expired_entries_periodically
from polixis_mcp.persistence import open_persistence
from polixis_mcp.persistence import Persistence
from polixis_mcp.upstream import open_upstream
from polixis_mcp.upstream import upstream_http
from polixis_mcp.upstream import upstream_tools
from polixis_mcp.upstream import UpstreamSettings

INSTRUCTIONS = (
    "Looks up organizations and people in Polixis corporate data: search, profiles with "
    "sanctions and PEP flags, related parties, ultimate beneficial owners and top-down "
    "ownership, linked companies, sanctions exposure, the path between two parties, the "
    "flagged parties near one and court decisions. Start with `search_entities` when you have "
    "a name or identifier: every other tool takes a match's `pid`. When the user gives a pid "
    "from their own records, call `resolve_permanent_id` first and use the pid it returns. "
    "Results come ranked so the first page usually answers the "
    "question: a tool whose result has a `next_cursor` holds more, which you fetch by passing "
    "it back alone as `cursor` only when the question needs what is left. A field whose "
    "description starts with 'Computed by this MCP' is not sent by Polixis: this server derives "
    "it from Polixis's data as the description says, so say so when you report it and explain "
    "how from that description when asked. Every other field is Polixis's, renamed or "
    "reformatted. Every result's `freshness` says when it was put together and, in "
    "`cached_at`, when the cached Polixis answer it used was cached: when that is set and the "
    "age matters, as for sanctions or PEP status, tell the user the data is as of then."
)


def create_server(
    upstream: UpstreamSettings,
    persistence: Persistence,
    transport: httpx2.AsyncBaseTransport | None = None,
    *,
    auth: AuthProvider | None = None,
    rate_limit: RateLimitSettings | None = None,
) -> FastMCP:
    """Build the server. The tests pass their own `persistence` and `transport`."""
    http = upstream_http(upstream, transport, cache=persistence.response_cache)
    # Once per TTL, so an answer normally leaves Postgres within twice the TTL, but at least
    # hourly, so a long TTL does not hold back the deletion of the sign-in state's expired rows.
    cull_every = min(upstream.cache.ttl_seconds, 60 * 60)

    @asynccontextmanager
    async def lifespan(_: FastMCP) -> AsyncGenerator[dict[str, object]]:
        async with (
            open_upstream(http, upstream) as upstream_resource,
            open_persistence(persistence),
            asyncio.TaskGroup() as background,
        ):
            culling = background.create_task(
                cull_expired_entries_periodically(
                    persistence,
                    every=cull_every,
                    max_cache_bytes=upstream.cache.max_megabytes * 1_000_000,
                )
            )
            try:
                yield {"upstream": upstream_resource}
            finally:
                culling.cancel()

    # Every signed-in user shares the one set of Polixis credentials, whose rate limit and
    # circuit breaker one caller must not use up for the others.
    rate_limiting = (
        [RateLimitMiddleware(rate_limit, get_request_key=access_token_subject)]
        if rate_limit is not None
        else []
    )
    mcp = FastMCP(
        name="Polixis MCP",
        version=version("polixis-mcp"),
        instructions=INSTRUCTIONS,
        # An unexpected error, such as a database error with its SQL, reaches the client as the
        # tool's name alone. A ToolError still reaches it as raised.
        mask_error_details=True,
        lifespan=lifespan,
        auth=auth,
        # Outermost: its log lines replace FastMCP's per-call lines, which can quote the input.
        middleware=[
            ToolCallObservabilityMiddleware(),
            *rate_limiting,
            SpecToolErrors(),
            FreshnessTracking(),
        ],
    )
    mcp.add_provider(upstream_tools(http))
    tools = FileSystemProvider(Path(__file__).parent / "tools")
    assert not tools.failed_files, f"tool files failed to load: {dict(tools.failed_files)}"
    mcp.add_provider(tools)
    validate_trace_declarations()
    return mcp
