from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path

import httpx2
import yaml
from fastmcp import FastMCP
from fastmcp.server.providers import FileSystemProvider
from mcp_openapi.upstream import OperationClient

from kyckr_mcp.client import create_client
from kyckr_mcp.instructions import INSTRUCTIONS
from kyckr_mcp.openapi.routes import CLIENT_BACKED
from kyckr_mcp.orders import DOWNLOAD_ORDER
from kyckr_mcp.settings import Settings

SPEC = yaml.safe_load((Path(__file__).parent / "openapi" / "kyckr-openapi.yml").read_text())


def create_server(
    settings: Settings, transport: httpx2.AsyncBaseTransport | None = None
) -> FastMCP:
    @asynccontextmanager
    async def lifespan(_: FastMCP) -> AsyncIterator[dict[str, object]]:
        async with create_client(settings, transport) as http:
            api = OperationClient(SPEC, http)
            missing = {*CLIENT_BACKED, DOWNLOAD_ORDER.operation_id} - api.operation_ids
            assert not missing, f"operationIds not in the spec: {sorted(missing)}"
            yield {"api": api, "settings": settings}

    mcp = FastMCP(
        name="Kyckr MCP",
        version=version("kyckr-mcp"),
        instructions=INSTRUCTIONS,
        lifespan=lifespan,
    )
    tools = FileSystemProvider(Path(__file__).parent / "tools")
    assert not tools.failed_files, f"tool files failed to load: {dict(tools.failed_files)}"
    mcp.add_provider(tools)
    return mcp
