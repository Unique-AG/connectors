# mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00

from collections.abc import AsyncGenerator

from fastmcp import Client
from fastmcp import FastMCP
import httpx2
from mcp_configs import ServerSettings
from pydantic import AnyHttpUrl
from pydantic import TypeAdapter
import pytest

from polixis_mcp.persistence import Persistence
from polixis_mcp.upstream import UpstreamSettings
from tests import polixis_responses
from tests.offline_server import build_server
from tests.offline_server import fake_upstream_settings
from tests.offline_server import open_fake_persistence
from tests.tool_calls import McpClient

_COMPLETION_FIELDS = TypeAdapter(dict[str, list[str]])
_PATH_REQUEST = TypeAdapter(dict[str, str])


@pytest.fixture
def server_settings() -> ServerSettings:
    """Every field given, so neither the environment nor `.env` changes what the tests see."""
    return ServerSettings(
        host="127.0.0.1",
        port=8000,
        mcp_base_url=AnyHttpUrl("http://127.0.0.1:8000"),
        mcp_allowed_origins=[AnyHttpUrl("http://localhost:6274")],
    )


@pytest.fixture
def upstream_settings() -> UpstreamSettings:
    return fake_upstream_settings()


@pytest.fixture
def upstream_requests() -> list[httpx2.Request]:
    """Every request the fake upstream answered, the token requests included."""
    return []


@pytest.fixture
def upstream_transport(upstream_requests: list[httpx2.Request]) -> httpx2.MockTransport:
    """Stands in for Polixis with the responses in `polixis_responses`. Like Polixis, it answers
    an id it does not know with a 200 and an error body.
    """

    def respond(request: httpx2.Request) -> httpx2.Response:
        upstream_requests.append(request)
        path = request.url.path
        if request.url.host == "auth.example.com":
            return httpx2.Response(200, json={"access_token": "fake-token", "expires_in": 300})
        if polixis_responses.UNKNOWN_PID in path or polixis_responses.UNKNOWN_PID.encode() in (
            request.content
        ):
            return httpx2.Response(200, json=polixis_responses.REJECTION)
        failing = polixis_responses.FAILING_PID
        if path == f"/api/completion/{failing}" or (
            path == "/api/graph/subgraph" and failing.encode() in request.content
        ):
            return httpx2.Response(500, json={"message": "Internal server error"})
        match path.rsplit("/", 1):
            case ["/search", "api"]:
                return httpx2.Response(200, json=polixis_responses.SEARCH)
            case ["/api/corporate", "byPublisher"]:
                return httpx2.Response(200, json=polixis_responses.RELATED_PARTIES)
            case ["/api/graph/ubo", _]:
                return httpx2.Response(200, json=polixis_responses.OWNERS)
            case ["/api/graph/topdown", _]:
                return httpx2.Response(200, json=polixis_responses.HOLDINGS)
            case ["/api/graph", "smart"]:
                return httpx2.Response(200, json=polixis_responses.KEY_GRAPH)
            case ["/api/graph", "subgraph"]:
                return httpx2.Response(200, json=polixis_responses.FULL_GRAPH)
            case ["/api/graph", "path"]:
                target = _PATH_REQUEST.validate_json(request.content)["targetId"]
                found = (
                    polixis_responses.PATHS
                    if target == "P00000000000000000000000000000400"
                    else polixis_responses.NO_PATHS
                )
                return httpx2.Response(200, json=found)
            case ["/api/sanction", _]:
                return httpx2.Response(200, json=polixis_responses.SANCTION_EXPOSURE)
            case ["/api/judicial", _]:
                return httpx2.Response(200, json=polixis_responses.JUDICIAL)
            case ["/api/completion", _]:
                fields = _COMPLETION_FIELDS.validate_json(request.content)["fields"]
                profile = polixis_responses.PROFILE
                return httpx2.Response(
                    200, json={field: profile[field] for field in fields if field in profile}
                )
            case _:
                return httpx2.Response(404)

    return httpx2.MockTransport(respond)


@pytest.fixture
async def persistence() -> AsyncGenerator[Persistence]:
    async with open_fake_persistence() as fake:
        yield fake


@pytest.fixture
def server(
    upstream_settings: UpstreamSettings,
    persistence: Persistence,
    upstream_transport: httpx2.MockTransport,
) -> FastMCP:
    return build_server(upstream_settings, persistence, upstream_transport)


@pytest.fixture
async def mcp_client(server: FastMCP) -> AsyncGenerator[McpClient]:
    async with Client(server) as client:
        yield client
