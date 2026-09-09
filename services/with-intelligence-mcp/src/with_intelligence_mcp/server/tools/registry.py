"""Registered MCP tools."""

from collections.abc import Awaitable, Callable

type ToolFunction = Callable[..., Awaitable[object]]

TOOLS: tuple[ToolFunction, ...] = ()
