from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.providers import FileSystemProvider
import httpx2

from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import open_upstream
from architecture_demo_mcp.upstream import upstream_http
from architecture_demo_mcp.upstream import upstream_tools
from architecture_demo_mcp.upstream import UpstreamSettings

INSTRUCTIONS = (
    "Reference MCP showing every scaffold layer: Tiingo market data through OpenAPI, with "
    "Postgres and Redis persistence. Copy its patterns; do not deploy it. Find a ticker with "
    "`search_assets` first, since every other tool takes the ticker it returns."
)


def create_server(
    upstream: UpstreamSettings,
    open_persistence: Callable[[], AbstractAsyncContextManager[Persistence]],
    transport: httpx2.AsyncBaseTransport | None = None,
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
        lifespan=lifespan,
        mask_error_details=True,
    )
    mcp.add_provider(upstream_tools(http))
    tools = FileSystemProvider(Path(__file__).parent / "tools")
    assert not tools.failed_files, f"tool files failed to load: {dict(tools.failed_files)}"
    mcp.add_provider(tools)
    return mcp
