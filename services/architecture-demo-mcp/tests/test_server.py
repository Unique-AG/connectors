from collections.abc import Iterator

from fastmcp import FastMCP
from mcp_runtime import http_app
from mcp_runtime import ServerSettings
import pytest
from starlette.testclient import TestClient

from architecture_demo_mcp.mcp import http_middleware

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}


@pytest.fixture
def client(server: FastMCP, server_settings: ServerSettings) -> Iterator[TestClient]:
    app = http_app(server, server_settings, http_middleware(server))
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("path", ["/probe", "/health", "/metrics"])
def test_ops_routes_answer_a_pod_ip_host(client: TestClient, path: str) -> None:
    assert client.get(path, headers={"Host": "10.1.2.3:8000"}).status_code == 200


def test_mcp_route_answers_a_local_host(client: TestClient) -> None:
    headers = {**MCP_HEADERS, "Host": "127.0.0.1:8000"}

    assert client.post("/mcp", json=PING, headers=headers).status_code == 200


def test_mcp_route_rejects_an_unknown_host(client: TestClient) -> None:
    headers = {**MCP_HEADERS, "Host": "10.1.2.3:8000"}

    assert client.post("/mcp", json=PING, headers=headers).status_code == 421


def test_mcp_route_rejects_an_unknown_origin(client: TestClient) -> None:
    headers = {**MCP_HEADERS, "Host": "127.0.0.1:8000", "Origin": "https://evil.example.com"}

    assert client.post("/mcp", json=PING, headers=headers).status_code == 403
