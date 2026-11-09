# mcp-scaffold-commit: f07e25a209f4, timestamp: 2026-11-09T11:34:03+00:00

from collections.abc import AsyncGenerator

from fastmcp import FastMCP
import httpx2
from mcp_configs import ServerSettings
from pydantic import AnyHttpUrl
import pytest

from polixis_mcp.persistence import Persistence
from polixis_mcp.upstream import UpstreamSettings
from tests.offline_server import build_server
from tests.offline_server import fake_upstream_settings
from tests.offline_server import open_fake_persistence


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


SEARCH_RESPONSE = {
    "hits": [
        {
            "pid": "P100",
            "entityType": "ORGANIZATION",
            "names": ["Example Holdings AG", "Example Holdings SA"],
            "sanction": True,
            "pep": False,
            "alerts": [{"description": "Listed company", "type": ["listed"]}],
            "unis": {"Registration Number": ["CHE-000.000.001"]},
            "sanctionStatuses": {"Example Sanctions List": "ACTIVE"},
        },
        {"entityType": "PERSON", "names": ["A hit without a pid"]},
    ],
    "pagination": {"page": 1, "size": 10, "totalHits": 2},
}


@pytest.fixture
def upstream_requests() -> list[httpx2.Request]:
    """Every request the fake upstream answered, the token requests included."""
    return []


@pytest.fixture
def upstream_transport(upstream_requests: list[httpx2.Request]) -> httpx2.MockTransport:
    """Stands in for Polixis: its token endpoint and the search the tools call."""

    def respond(request: httpx2.Request) -> httpx2.Response:
        upstream_requests.append(request)
        match (request.method, request.url.host, request.url.path):
            case ("POST", "auth.example.com", "/token"):
                return httpx2.Response(200, json={"access_token": "fake-token", "expires_in": 300})
            case ("POST", "api.example.com", "/search/api"):
                return httpx2.Response(200, json=SEARCH_RESPONSE)
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
