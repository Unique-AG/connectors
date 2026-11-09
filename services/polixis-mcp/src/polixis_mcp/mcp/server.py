# mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager
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

from polixis_mcp.persistence import Persistence
from polixis_mcp.upstream import open_upstream
from polixis_mcp.upstream import upstream_http
from polixis_mcp.upstream import upstream_tools
from polixis_mcp.upstream import UpstreamSettings

INSTRUCTIONS = (
    "Looks up organizations and people in Polixis corporate data: search, corporate "
    "profiles with their related parties, relationship graphs, top-down ownership and "
    "ultimate beneficial owners, and sanctions and PEP flags."
)


def create_server(
    upstream: UpstreamSettings,
    open_persistence: Callable[[], AbstractAsyncContextManager[Persistence]],
    transport: httpx2.AsyncBaseTransport | None = None,
    *,
    auth: AuthProvider | None = None,
    rate_limit: RateLimitSettings | None = None,
) -> FastMCP:
    """Build the server. `open_persistence` opens every store, so the tests can open their own."""
    http = upstream_http(upstream, transport)

    @asynccontextmanager
    async def lifespan(_: FastMCP) -> AsyncGenerator[dict[str, object]]:
        async with (
            open_upstream(http, upstream) as upstream_resource,
            open_persistence() as persistence_resource,
        ):
            yield {"upstream": upstream_resource, "persistence": persistence_resource}

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
        middleware=[ToolCallObservabilityMiddleware(), *rate_limiting],
    )
    mcp.add_provider(upstream_tools(http))
    tools = FileSystemProvider(Path(__file__).parent / "tools")
    assert not tools.failed_files, f"tool files failed to load: {dict(tools.failed_files)}"
    mcp.add_provider(tools)
    validate_trace_declarations()
    return mcp
