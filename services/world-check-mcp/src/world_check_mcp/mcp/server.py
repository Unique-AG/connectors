# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-22T06:27:45+00:00

from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider
from fastmcp.server.providers import FileSystemProvider
import httpx2

from world_check_mcp.mcp.approval import ApprovalGate
from world_check_mcp.persistence import Persistence
from world_check_mcp.upstream import open_upstream
from world_check_mcp.upstream import upstream_http
from world_check_mcp.upstream import upstream_tools
from world_check_mcp.upstream import UpstreamSettings

INSTRUCTIONS = (
    "Screens people and organizations in LSEG World-Check One and returns sanctions, PEP, "
    "and adverse-media results for KYC and third-party due diligence."
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
            yield {
                "upstream": upstream_resource,
                "persistence": persistence_resource,
                "approvals": ApprovalGate(),
            }

    mcp = FastMCP(
        name="World Check MCP",
        version=version("world-check-mcp"),
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
