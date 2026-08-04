from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.providers import FileSystemProvider

from q_bridge_mcp.auth import setup_auth
from q_bridge_mcp.profiles import profile_app

SERVER_INSTRUCTIONS = (
    "Before using Q Bridge tools, call profile_settings so the user can complete "
    "their profile and organization setup. If a tool reports that setup is "
    "incomplete, call profile_settings and ask the user to finish the form."
)


def create_server() -> FastMCP:
    provider = FileSystemProvider(Path(__file__).parent / "tools")
    return FastMCP(
        name="q-bridge-mcp",
        instructions=SERVER_INSTRUCTIONS,
        auth=setup_auth(),
        providers=[provider, profile_app],
    )
