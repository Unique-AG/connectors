"""The server with fakes in place of the upstream and the stores.

The tests build it, and so does `uv run poe architecture`, which lists its tools.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from pydantic import HttpUrl
from pydantic import SecretStr

from space_config_mcp.mcp import AuthSettings
from space_config_mcp.mcp import create_server
from space_config_mcp.persistence import PersistenceSettings
from space_config_mcp.upstream import UpstreamSettings


def fake_upstream_settings() -> UpstreamSettings:
    """Every field given, so neither the environment nor `.env` changes what the tests see."""
    return UpstreamSettings(
        unique_api_key=SecretStr("dummy-api-key"),
        unique_app_id="dummy-app-id",
    )


def fake_persistence_settings() -> PersistenceSettings:
    return PersistenceSettings()


def fake_auth_settings() -> AuthSettings:
    """Ephemeral OAuth storage — suitable for offline tests only."""
    return AuthSettings(
        public_base_url=HttpUrl("http://localhost:8000"),
        zitadel_base_url="https://id.qa.unique.app",
        zitadel_client_id="dummy-client-id",
        zitadel_jwt_signing_key=SecretStr("a" * 64),
        database_url=None,
        encryption_key=None,
        allow_ephemeral_oauth_storage=True,
    )


def build_server(
    upstream_settings: UpstreamSettings | None = None,
    persistence_settings: PersistenceSettings | None = None,
    auth_settings: AuthSettings | None = None,
) -> FastMCP:
    return create_server(
        upstream_settings or fake_upstream_settings(),
        persistence_settings or fake_persistence_settings(),
        auth_settings or fake_auth_settings(),
    )


@asynccontextmanager
async def offline_server() -> AsyncGenerator[FastMCP]:
    yield build_server()
