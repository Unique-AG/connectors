import asyncio
from collections.abc import Awaitable, Callable

import httpx2
from fastmcp import Client, FastMCP
from fastmcp.client.client import CallToolResult

from kyckr_mcp.server import create_server
from kyckr_mcp.settings import Settings

Handler = Callable[[httpx2.Request], Awaitable[httpx2.Response]]


def build_server(settings: Settings, handler: Handler) -> FastMCP:
    return create_server(settings, httpx2.MockTransport(handler))


def call_tool(
    settings: Settings, handler: Handler, name: str, arguments: dict[str, object]
) -> CallToolResult:
    async def call() -> CallToolResult:
        async with Client(build_server(settings, handler)) as client:
            return await client.call_tool(name, arguments, raise_on_error=False)

    return asyncio.run(call())
