"""The single declaration of which tools this server exposes.

Each entry is a `@tool`-decorated function (annotations / glossary meta live on the function).
`create_app` registers from this list via `mcp.add_tool`. Empty for now — the first tools land
once `features/custom_fields` and `features/party_resolver` do, in a later PR.
"""

from collections.abc import Awaitable, Callable

from mcp.types import CallToolResult

type ToolFunction = Callable[..., Awaitable[CallToolResult]]

TOOLS: tuple[ToolFunction, ...] = ()
