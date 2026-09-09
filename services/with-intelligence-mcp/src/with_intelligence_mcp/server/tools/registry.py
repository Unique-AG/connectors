"""The single declaration of which tools this server exposes.

Each entry is a `@tool`-decorated function (annotations live on the function). `create_app`
registers from this list via `mcp.add_tool`. A tool module that exists but is not listed here
fails `tests/test_layering.py` rather than shipping unreachable.
"""

from collections.abc import Awaitable, Callable

type ToolFunction = Callable[..., Awaitable[object]]

TOOLS: tuple[ToolFunction, ...] = ()
