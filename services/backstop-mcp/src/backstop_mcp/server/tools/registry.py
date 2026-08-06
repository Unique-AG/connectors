"""The single declaration of which tools this server exposes.

Each entry is a `@tool`-decorated function (annotations / glossary meta live on the function).
`create_app` registers from this list via `mcp.add_tool`. Glossary scopes are read from tool
`meta` at tools/list time — not restated here.
"""

from collections.abc import Awaitable, Callable

from mcp.types import CallToolResult

from backstop_mcp.server.tools.get_organization import get_organization
from backstop_mcp.server.tools.get_person import get_person
from backstop_mcp.server.tools.list_custom_fields import list_custom_fields
from backstop_mcp.server.tools.system_info import get_system_info

type ToolFunction = Callable[..., Awaitable[CallToolResult]]

TOOLS: tuple[ToolFunction, ...] = (
    get_system_info,
    get_organization,
    get_person,
    list_custom_fields,
)
