from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.providers import FileSystemProvider

from q_bridge_mcp.auth import setup_auth


def create_server() -> FastMCP:
    provider = FileSystemProvider(Path(__file__).parent / "tools")
    return FastMCP(
        name="q-bridge-mcp",
        auth=setup_auth(),
        providers=[provider],
    )
