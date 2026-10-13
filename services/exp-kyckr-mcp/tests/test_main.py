import asyncio
from collections.abc import Generator

import httpx2
import pytest
from fastmcp import FastMCP
from starlette.testclient import TestClient
from unique_mcp.monitoring import setup_ops

from kyckr_mcp.main import OPS_PATHS, host_origin_guard
from kyckr_mcp.server import create_server
from kyckr_mcp.settings import Settings
from kyckr_mcp.tools import register_tools

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}


@pytest.fixture
def client(
    settings: Settings,
    spec: dict[str, object],
) -> Generator[TestClient, None, None]:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"data": []})

    upstream = httpx2.AsyncClient(
        base_url="https://test-api.kyckr.com/v2",
        transport=httpx2.MockTransport(handler),
    )
    mcp: FastMCP = create_server(settings, spec=spec, client=upstream)
    asyncio.run(register_tools(mcp, settings))
    ops_middleware = setup_ops(mcp)
    app = mcp.http_app(
        path=settings.mcp_path,
        transport="streamable-http",
        stateless_http=True,
        host_origin_protection=False,
        middleware=[host_origin_guard(settings, []), ops_middleware],
    )
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        asyncio.run(upstream.aclose())


def test_ops_routes_are_available(client: TestClient) -> None:
    for path in sorted(OPS_PATHS):
        assert client.get(path, headers={"Host": "10.1.2.3:9542"}).status_code == 200


def test_mcp_route_checks_host(client: TestClient) -> None:
    headers = {**MCP_HEADERS, "Host": "10.1.2.3:9542"}
    assert client.post("/test-mcp-key/mcp", json=PING, headers=headers).status_code == 421


def test_mcp_route_checks_origin(client: TestClient) -> None:
    headers = {
        **MCP_HEADERS,
        "Host": "127.0.0.1:9542",
        "Origin": "https://evil.example.com",
    }
    assert client.post("/test-mcp-key/mcp", json=PING, headers=headers).status_code == 403
