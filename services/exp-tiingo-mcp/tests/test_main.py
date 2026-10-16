import pytest
from starlette.testclient import TestClient

from tiingo_mcp.main import OPS_PATHS, host_origin_guard
from tiingo_mcp.server import create_server
from tiingo_mcp.settings import Settings

PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture
def client(local_settings: Settings) -> TestClient:
    from unique_mcp.monitoring import setup_ops

    mcp = create_server(local_settings)
    setup_ops(mcp)
    app = mcp.http_app(
        path="/mcp",
        transport="streamable-http",
        stateless_http=True,
        host_origin_protection=False,
        middleware=[host_origin_guard(local_settings, [])],
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("path", sorted(OPS_PATHS))
def test_ops_routes_answer_to_any_host(client: TestClient, path: str) -> None:
    assert client.get(path, headers={"Host": "10.1.2.3:8741"}).status_code == 200


def test_mcp_route_still_checks_the_host(client: TestClient) -> None:
    def ping(host: str) -> int:
        return client.post("/mcp", json=PING, headers={**MCP_HEADERS, "Host": host}).status_code

    assert ping("localhost:8741") == 200
    assert ping("10.1.2.3:8741") == 421


def test_mcp_route_still_checks_the_origin(client: TestClient) -> None:
    headers = {**MCP_HEADERS, "Host": "localhost:8741", "Origin": "https://evil.example.com"}
    assert client.post("/mcp", json=PING, headers=headers).status_code == 403
