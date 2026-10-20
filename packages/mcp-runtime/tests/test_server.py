from collections.abc import Iterator

import pytest
from fastmcp import FastMCP
from pydantic import AnyHttpUrl, ValidationError
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.testclient import TestClient
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from mcp_runtime import ServerSettings, http_app

MCP_HEADERS = {"Accept": "application/json, text/event-stream"}
PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
LOCAL_HOST = "127.0.0.1:8000"
POD_IP_HOST = "10.1.2.3:8000"


class TaggingMiddleware:
    """Stands in for an MCP's own middleware: marks each response it sees."""

    def __init__(self, app: ASGIApp) -> None:
        self.app: ASGIApp = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def tagged(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message["headers"], (b"x-own", b"seen")]
            await send(message)

        await self.app(scope, receive, tagged)


@pytest.fixture
def client() -> Iterator[TestClient]:
    mcp = FastMCP(name="Probe")

    @mcp.custom_route("/probe", methods=["GET"])
    async def probe(_: Request) -> Response:
        return PlainTextResponse("ok")

    app = http_app(mcp, ServerSettings(), [Middleware(TaggingMiddleware)])
    with TestClient(app) as test_client:
        yield test_client


def test_an_ops_route_answers_a_pod_ip_host(client: TestClient) -> None:
    assert client.get("/probe", headers={"Host": POD_IP_HOST}).status_code == 200


def test_the_mcp_route_answers_a_local_host(client: TestClient) -> None:
    response = client.post("/mcp", json=PING, headers={**MCP_HEADERS, "Host": LOCAL_HOST})

    assert response.status_code == 200


def test_the_mcp_route_rejects_an_unknown_host(client: TestClient) -> None:
    response = client.post("/mcp", json=PING, headers={**MCP_HEADERS, "Host": POD_IP_HOST})

    assert response.status_code == 421


def test_the_mcp_route_rejects_an_unknown_origin(client: TestClient) -> None:
    headers = {**MCP_HEADERS, "Host": LOCAL_HOST, "Origin": "https://evil.example.com"}

    assert client.post("/mcp", json=PING, headers=headers).status_code == 403


def test_the_mcps_own_middleware_runs_after_the_guard(client: TestClient) -> None:
    allowed = client.post("/mcp", json=PING, headers={**MCP_HEADERS, "Host": LOCAL_HOST})
    rejected = client.post("/mcp", json=PING, headers={**MCP_HEADERS, "Host": POD_IP_HOST})

    assert allowed.headers["x-own"] == "seen"
    assert "x-own" not in rejected.headers


def test_cors_lets_a_browser_client_read_the_auth_and_session_headers(client: TestClient) -> None:
    headers = {**MCP_HEADERS, "Host": LOCAL_HOST, "Origin": "http://localhost:6274"}

    response = client.post("/mcp", json=PING, headers=headers)

    assert response.headers["access-control-expose-headers"] == "WWW-Authenticate, Mcp-Session-Id"


def test_server_settings_default_to_a_local_origin_and_the_inspector() -> None:
    settings = ServerSettings()

    assert settings.base_url == "http://127.0.0.1:8000"
    assert settings.allowed_hosts == ["localhost", "127.0.0.1"]
    assert settings.allowed_origins == ["http://localhost:6274"]


def test_server_settings_allow_only_the_public_host_when_deployed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_BASE_URL", "https://weather.example.com")

    settings = ServerSettings()

    assert settings.allowed_hosts == ["weather.example.com"]
    assert settings.allowed_origins == []


@pytest.mark.parametrize(
    ("url", "message"),
    [
        ("https://weather.example.com/mcp", "bare origin"),
        ("http://weather.example.com", "requires HTTPS"),
    ],
)
def test_server_settings_reject_a_base_url_that_is_not_a_public_https_origin(
    url: str, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        ServerSettings(mcp_base_url=AnyHttpUrl(url))
