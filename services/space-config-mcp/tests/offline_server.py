"""The server with fakes in place of the upstream and the stores.

The tests build it, and so does `uv run poe architecture`, which lists its tools.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from pydantic import SecretStr

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
    return PersistenceSettings(history_folder="_space-config-history-test")


def build_server(
    upstream_settings: UpstreamSettings | None = None,
    persistence_settings: PersistenceSettings | None = None,
) -> FastMCP:
    return create_server(
        upstream_settings or fake_upstream_settings(),
        persistence_settings or fake_persistence_settings(),
    )


@asynccontextmanager
async def offline_server() -> AsyncGenerator[FastMCP]:
    yield build_server()
