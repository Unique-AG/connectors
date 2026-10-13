from fastmcp import FastMCP

from kyckr_mcp.settings import Settings
from kyckr_mcp.tools.kyckr import register


async def register_tools(mcp: FastMCP, settings: Settings) -> None:
    await register(mcp, settings)
