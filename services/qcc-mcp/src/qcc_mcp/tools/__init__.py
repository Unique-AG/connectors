"""Tool registry — the whole of what this connector exposes.

Each module has a `register(mcp, client)`; `register_tools` calls them in a
stable order. Add a new tool by writing its module and appending it here.
"""

from __future__ import annotations

from fastmcp import FastMCP

from qcc_mcp.client import QccClient
from qcc_mcp.tools import drill, reports, search

_MODULES = (search, reports, drill)


def register_tools(mcp: FastMCP, client: QccClient) -> None:
    for module in _MODULES:
        module.register(mcp, client)
