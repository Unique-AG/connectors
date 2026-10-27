from collections.abc import Generator

import httpx2
import pytest
from starlette.testclient import TestClient

from kyckr_mcp.main import http_options
from kyckr_mcp.settings import Settings
from tests.support import build_server

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}


@pytest.fixture
def client(settings: Settings) -> Generator[TestClient]:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"data": []})

    mcp = build_server(settings, handler)
    app = mcp.http_app(transport="streamable-http", **http_options(mcp, settings))
    with TestClient(app) as test_client:
        yield test_client


def test_ops_routes_are_available(client: TestClient) -> None:
    for path in ("/probe", "/health", "/metrics"):
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


def test_metrics_do_not_expose_the_mcp_api_key(client: TestClient) -> None:
    headers = {**MCP_HEADERS, "Host": "127.0.0.1:9542"}
    assert client.post("/test-mcp-key/mcp", json=PING, headers=headers).status_code == 200

    metrics = client.get("/metrics", headers={"Host": "127.0.0.1:9542"}).text

    assert "test-mcp-key" not in metrics
    assert 'path="/:mcpApiKey/mcp"' in metrics
