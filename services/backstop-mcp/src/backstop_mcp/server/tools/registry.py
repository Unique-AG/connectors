"""The single declaration of which tools this server exposes.

Each entry is a `@tool`-decorated function (annotations / glossary meta live on the function).
`create_app` registers from this list via `mcp.add_tool`. Empty for now — the client, auth, and
party-resolver library land here across earlier PRs with nothing wired to MCP yet; the first
tools land once `custom_fields` and the rest of the domain logic are in place.
"""

from collections.abc import Awaitable, Callable

from mcp.types import CallToolResult

type ToolFunction = Callable[..., Awaitable[CallToolResult]]

TOOLS: tuple[ToolFunction, ...] = ()
