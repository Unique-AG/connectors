import asyncio
import re

import httpx2
from fastmcp import Client

from tiingo_mcp.server import INSTRUCTIONS, create_server, strip_forwarded_headers
from tiingo_mcp.settings import Settings
from tiingo_mcp.tools import register_tools


def test_every_tool_is_marked_read_only_and_the_server_has_instructions(
    local_settings: Settings,
) -> None:
    async def list_tools():  # noqa: ANN202
        mcp = create_server(local_settings)
        await register_tools(mcp)
        async with Client(mcp) as client:
            return mcp, await client.list_tools()

    mcp, tools = asyncio.run(list_tools())
    assert mcp.instructions == INSTRUCTIONS
    assert all(re.fullmatch(r"[a-z0-9_]+", tool.name) for tool in tools)
    assert tools and all(tool.annotations and tool.annotations.read_only_hint for tool in tools)


def test_only_vendor_request_headers_leave_for_tiingo() -> None:
    request = httpx2.Request(
        "GET",
        "https://api.tiingo.com/api/test",
        headers={
            "Authorization": "Token k",
            "X-Forwarded-For": "203.0.113.9",
            "Origin": "https://client.example",
        },
    )
    asyncio.run(strip_forwarded_headers(request))
    assert request.headers["authorization"] == "Token k"
    assert "x-forwarded-for" not in request.headers
    assert "origin" not in request.headers
