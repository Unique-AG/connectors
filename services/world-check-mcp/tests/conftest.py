# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-22T06:27:45+00:00

from fastmcp import FastMCP
import httpx2
from mcp_configs import ServerSettings
from pydantic import AnyHttpUrl
import pytest

from tests.offline_server import build_server
from tests.offline_server import fake_upstream_settings
from tests.offline_server import unanswered_upstream
from world_check_mcp.upstream import UpstreamSettings


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
def upstream_transport() -> httpx2.MockTransport:
    """Stands in for the upstream.

    Answer each route the tools call with fixed data.
    """
    return unanswered_upstream()


@pytest.fixture
def server(
    upstream_settings: UpstreamSettings, upstream_transport: httpx2.MockTransport
) -> FastMCP:
    return build_server(upstream_settings, upstream_transport)
