# mcp-scaffold-commit: 6474bb8667dc, timestamp: 2026-11-16T10:36:30+00:00

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
from mcp_observability import RedactToolCallSecretsMiddleware
from mcp_observability import ToolCallObservabilityMiddleware
from mcp_observability import validate_trace_declarations

from kyckr_mcp.mcp.instructions import INSTRUCTIONS
from kyckr_mcp.persistence import Persistence
from kyckr_mcp.upstream import open_upstream
from kyckr_mcp.upstream import upstream_http
from kyckr_mcp.upstream import UpstreamSettings


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
            yield {
                "upstream": upstream_resource,
                "upstream_settings": upstream,
                "persistence": persistence_resource,
            }

    # Every signed-in user shares one Kyckr key, so one caller must not spend the others' credits.
    rate_limiting = (
        [RateLimitMiddleware(rate_limit, get_request_key=access_token_subject)]
        if rate_limit is not None
        else []
    )
    mcp = FastMCP(
        name="Kyckr MCP",
        version=version("kyckr-mcp"),
        instructions=INSTRUCTIONS,
        # An unexpected error, such as a database error with its SQL, reaches the client as the
        # tool's name alone. A ToolError still reaches it as raised.
        mask_error_details=True,
        # Redaction outermost, so the caller's access token is redacted from the tool-call lines.
        # The tool-call lines replace FastMCP's per-call lines, which can quote the input.
        middleware=[
            RedactToolCallSecretsMiddleware(),
            ToolCallObservabilityMiddleware(),
            *rate_limiting,
        ],
        lifespan=lifespan,
        auth=auth,
    )
    tools = FileSystemProvider(Path(__file__).parent / "tools")
    assert not tools.failed_files, f"tool files failed to load: {dict(tools.failed_files)}"
    mcp.add_provider(tools)
    validate_trace_declarations()
    return mcp
