from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from fastmcp.server.providers import FileSystemProvider

from space_config_mcp.mcp.auth import build_auth
from space_config_mcp.mcp.auth.settings import AuthSettings
from space_config_mcp.persistence import open_persistence
from space_config_mcp.persistence import PersistenceSettings
from space_config_mcp.upstream import open_upstream
from space_config_mcp.upstream import UpstreamSettings

INSTRUCTIONS = "Read and update Unique AI space and module configuration"


def create_server(
    upstream: UpstreamSettings,
    persistence: PersistenceSettings,
    auth_settings: AuthSettings | None = None,
) -> FastMCP:
    oidc_proxy: OIDCProxy | None = build_auth(auth_settings) if auth_settings is not None else None

    @asynccontextmanager
    async def lifespan(_: FastMCP) -> AsyncGenerator[dict[str, object]]:
        async with (
            open_upstream(upstream) as upstream_resource,
            open_persistence(persistence) as persistence_resource,
        ):
            yield {"upstream": upstream_resource, "persistence": persistence_resource}

    mcp = FastMCP(
        name="Space Config MCP",
        version=version("space-config-mcp"),
        instructions=INSTRUCTIONS,
        auth=oidc_proxy,
        mask_error_details=True,
        lifespan=lifespan,
    )
    tools = FileSystemProvider(Path(__file__).parent / "tools")
    assert not tools.failed_files, f"tool files failed to load: {dict(tools.failed_files)}"
    mcp.add_provider(tools)
    return mcp
