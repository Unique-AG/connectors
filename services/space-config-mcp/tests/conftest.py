from fastmcp import FastMCP
from mcp_configs import ServerSettings
from pydantic import AnyHttpUrl
import pytest

from space_config_mcp.persistence import PersistenceSettings
from space_config_mcp.upstream import UpstreamSettings
from tests.offline_server import build_server
from tests.offline_server import fake_persistence_settings
from tests.offline_server import fake_upstream_settings


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
def persistence_settings() -> PersistenceSettings:
    return fake_persistence_settings()


@pytest.fixture
def server(
    upstream_settings: UpstreamSettings,
    persistence_settings: PersistenceSettings,
) -> FastMCP:
    return build_server(upstream_settings, persistence_settings)
