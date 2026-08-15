"""The registry: every tool module and their shared permissions.

A tool is one file. It publishes `GRAPH_PERMISSIONS` (tuple) and `register` (function). Adding a
tool: one file plus one line here.

TRAP: `GRAPH_SCOPES` must be derived from modules, never hand-written. At startup, `create_app`
passes all permissions to the auth provider. A forgotten permission means sign-in fails with
AADSTS65001. Deriving it here guarantees every registered tool has consent.

Order is stable (via `dict.fromkeys`, not `set`) so token keys don't change on each restart.
"""

from typing import Protocol

import httpx
from fastmcp import FastMCP

from office_mcp.shared.seam import graph_scope
from office_mcp.tools import (
    get_me,
    list_channels,
    list_chats,
    list_teams,
    read_message,
    search_messages,
)

__all__ = ["GRAPH_SCOPES", "register_tools"]


class ToolModule(Protocol):
    """Contract a tool file must satisfy. Checked structurally: missing `GRAPH_PERMISSIONS` or
    `register` is a type error, not a runtime surprise."""

    GRAPH_PERMISSIONS: tuple[str, ...]

    @staticmethod
    def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None: ...


_TOOL_MODULES: tuple[ToolModule, ...] = (
    get_me,
    list_chats,
    list_teams,
    list_channels,
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
