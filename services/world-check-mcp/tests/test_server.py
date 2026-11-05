# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-22T06:27:45+00:00

from collections.abc import Iterator

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier
from mcp_configs import RateLimitSettings
from mcp_configs import ServerSettings
from mcp_observability import RateLimitMiddleware
from pydantic import AnyHttpUrl
import pytest
from starlette.testclient import TestClient

from tests.offline_server import fake_elicitation_settings
from tests.offline_server import fake_upstream_settings
from tests.offline_server import open_fake_persistence
from tests.offline_server import unanswered_upstream
from world_check_mcp.mcp import create_server
from world_check_mcp.mcp import http_app
from world_check_mcp.mcp import run_server

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
LOCAL_HOST = "127.0.0.1:8000"
POD_IP_HOST = "10.1.2.3:8000"
DEPLOYED = ServerSettings(
    host="0.0.0.0",
    port=8000,
    mcp_base_url=AnyHttpUrl("https://mcp.example.com"),
    mcp_allowed_origins=[],
)


@pytest.fixture
def client(server: FastMCP, server_settings: ServerSettings) -> Iterator[TestClient]:
    with TestClient(http_app(server, server_settings)) as test_client:
        yield test_client


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The hosts `FastMCP.run` was asked to bind, without binding them."""
    hosts: list[str] = []

    def run(_: FastMCP, **options: object) -> None:
        hosts.append(str(options["host"]))

    monkeypatch.setattr(FastMCP, "run", run)
    return hosts


@pytest.mark.parametrize("path", ["/probe", "/health", "/metrics"])
def test_ops_routes_answer_a_pod_ip_host(client: TestClient, path: str) -> None:
    assert client.get(path, headers={"Host": POD_IP_HOST}).status_code == 200


def test_mcp_route_answers_a_local_host(client: TestClient) -> None:
    headers = {**MCP_HEADERS, "Host": LOCAL_HOST}

    assert client.post("/mcp", json=PING, headers=headers).status_code == 200


def test_mcp_route_rejects_an_unknown_host(client: TestClient) -> None:
    headers = {**MCP_HEADERS, "Host": POD_IP_HOST}

    assert client.post("/mcp", json=PING, headers=headers).status_code == 421


def test_mcp_route_rejects_an_unknown_origin(client: TestClient) -> None:
    headers = {**MCP_HEADERS, "Host": LOCAL_HOST, "Origin": "https://evil.example.com"}

    assert client.post("/mcp", json=PING, headers=headers).status_code == 403


def test_cors_lets_a_browser_client_read_the_auth_and_session_headers(client: TestClient) -> None:
    headers = {**MCP_HEADERS, "Host": LOCAL_HOST, "Origin": "http://localhost:6274"}

    response = client.post("/mcp", json=PING, headers=headers)

    assert response.headers["access-control-expose-headers"] == "WWW-Authenticate, Mcp-Session-Id"


def test_a_server_without_auth_refuses_to_serve_beyond_loopback(
    server: FastMCP, served: list[str]
) -> None:
    with pytest.raises(RuntimeError, match="has no auth provider"):
        run_server(server, DEPLOYED)

    assert served == []


def test_a_server_without_auth_serves_on_loopback(
    server: FastMCP, server_settings: ServerSettings, served: list[str]
) -> None:
    run_server(server, server_settings)

    assert served == [server_settings.host]


def test_a_server_with_auth_serves_beyond_loopback(served: list[str]) -> None:
    run_server(FastMCP(name="Probe", auth=StaticTokenVerifier(tokens={})), DEPLOYED)

    assert served == ["0.0.0.0"]


def test_uvicorn_logs_through_the_pino_handler(
    server: FastMCP, server_settings: ServerSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    uvicorn_configs: list[object] = []

    def run(_: FastMCP, **options: object) -> None:
        uvicorn_configs.append(options["uvicorn_config"])

    monkeypatch.setattr(FastMCP, "run", run)

    run_server(server, server_settings)

    assert uvicorn_configs == [{"access_log": False, "log_config": None}]


@pytest.mark.parametrize(
    ("rate_limit", "limited"),
    [(RateLimitSettings(tool_calls_per_window=5, window_seconds=60), True), (None, False)],
)
def test_a_rate_limit_counts_the_tool_calls_of_each_user(
    rate_limit: RateLimitSettings | None, limited: bool
) -> None:
    server = create_server(
        fake_upstream_settings(),
        open_fake_persistence,
        unanswered_upstream(),
        elicitation=fake_elicitation_settings(),
        rate_limit=rate_limit,
    )
    assert any(isinstance(item, RateLimitMiddleware) for item in server.middleware) is limited
