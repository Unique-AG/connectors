# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-21T12:09:32+00:00

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider
from fastmcp.server.providers import FileSystemProvider
import httpx2

from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import open_upstream
from architecture_demo_mcp.upstream import upstream_http
from architecture_demo_mcp.upstream import upstream_tools
from architecture_demo_mcp.upstream import UpstreamSettings

INSTRUCTIONS = (
    "Market data from Tiingo, and the user's own portfolios. When you only have a company's "
    "name, find its ticker with `search_assets`. The other `get_` and `list_` tools answer "
    "straight from Tiingo: daily prices and listing details, real-time and crypto and forex "
    "quotes, fundamentals, news, dividends and splits. For how a ticker did over a period, its "
    "return, volatility, drawdown and range, call `get_price_performance` rather than working it "
    "out from daily prices. When the user says what they hold, call `record_position`: it stores "
    "the holding in one of their named portfolios and answers with the whole portfolio valued at "
    "the latest closes. Each user sees only their own portfolios."
)


def create_server(
    upstream: UpstreamSettings,
    open_persistence: Callable[[], AbstractAsyncContextManager[Persistence]],
    transport: httpx2.AsyncBaseTransport | None = None,
    *,
    auth: AuthProvider | None = None,
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

    mcp = FastMCP(
        name="Architecture Demo MCP",
        version=version("architecture-demo-mcp"),
        instructions=INSTRUCTIONS,
        # An unexpected error, such as a database error with its SQL, reaches the client as the
        # tool's name alone. A ToolError still reaches it as raised.
        mask_error_details=True,
        lifespan=lifespan,
        auth=auth,
    )
    mcp.add_provider(upstream_tools(http))
    tools = FileSystemProvider(Path(__file__).parent / "tools")
    assert not tools.failed_files, f"tool files failed to load: {dict(tools.failed_files)}"
    mcp.add_provider(tools)
    return mcp
