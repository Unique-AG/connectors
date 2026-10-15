import asyncio
import re
from functools import partial
from pathlib import Path

import httpx2
import pytest
from fastmcp import Client
from fastmcp.server.providers import FileSystemProvider
from starlette.testclient import TestClient

from tiingo_mcp import server
from tiingo_mcp.server import INSTRUCTIONS, create_server
from tiingo_mcp.settings import Settings


def test_every_tool_is_marked_read_only_and_the_server_has_instructions(
    local_settings: Settings,
) -> None:
    async def list_tools():  # noqa: ANN202
        mcp = create_server(local_settings)
        async with Client(mcp) as client:
            return mcp, await client.list_tools()

    mcp, tools = asyncio.run(list_tools())
    assert mcp.instructions == INSTRUCTIONS
    assert all(re.fullmatch(r"[a-z0-9_]+", tool.name) for tool in tools)
    assert tools and all(tool.annotations and tool.annotations.read_only_hint for tool in tools)


def test_a_tool_file_that_fails_to_import_stops_startup(
    local_settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "broken.py").write_text("raise RuntimeError('boom')\n")
    monkeypatch.setattr(server, "FileSystemProvider", lambda _: FileSystemProvider(tmp_path))
    with pytest.raises(AssertionError, match="tool files failed to load"):
        create_server(local_settings)


def test_only_vendor_request_headers_leave_for_tiingo(
    local_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=[])

    monkeypatch.setattr(
        server.httpx2,
        "AsyncClient",
        partial(httpx2.AsyncClient, transport=httpx2.MockTransport(handler)),
    )
    app = create_server(local_settings).http_app(
        path="/mcp", transport="streamable-http", stateless_http=True, host_origin_protection=False
    )
    call = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "search_assets", "arguments": {"query": "apple"}},
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "X-Forwarded-For": "203.0.113.9",
        "X-Custom": "1",
    }
    with TestClient(app) as client:
        client.post("/mcp", headers=headers, json=call)
    assert seen, "the tool call never reached the Tiingo transport"
    sent = seen[0].headers
    assert sent["authorization"] == "Token test"
    assert "x-forwarded-for" not in sent and "x-custom" not in sent
