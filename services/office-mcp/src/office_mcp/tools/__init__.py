"""The registry of all tools and their permissions.

Each tool is one file that publishes `GRAPH_PERMISSIONS` and `register`. Add a tool: one file
plus one line here.

TRAP: Derive `GRAPH_SCOPES` from modules, never hand-write it. `create_app` passes all permissions
to the auth provider at startup. A missing permission causes sign-in to fail with AADSTS65001.
Deriving here guarantees every tool has consent.

Order is stable (via `dict.fromkeys`, not `set`). This keeps token keys the same across restarts."""

from typing import Protocol

import httpx
from fastmcp import FastMCP

from office_mcp.shared.seam import graph_scope
from office_mcp.tools import (
    browse_channel,
    get_me,
    list_channels,
    list_chats,
    list_teams,
    read_message,
    search_messages,
)

__all__ = ["GRAPH_SCOPES", "register_tools"]


class ToolModule(Protocol):
    """Contract a tool must satisfy. Type-checked structurally at import."""

    GRAPH_PERMISSIONS: tuple[str, ...]

    @staticmethod
    def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None: ...


_TOOL_MODULES: tuple[ToolModule, ...] = (
    get_me,
    list_chats,
    list_teams,
    list_channels,
    browse_channel,
    search_messages,
    read_message,
)

GRAPH_SCOPES: tuple[str, ...] = tuple(
    dict.fromkeys(
        graph_scope(permission)
        for module in _TOOL_MODULES
        for permission in module.GRAPH_PERMISSIONS
    )
)


def register_tools(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    """Register every tool module."""
    for module in _TOOL_MODULES:
        module.register(mcp, transport)
