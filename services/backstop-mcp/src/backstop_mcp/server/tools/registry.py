"""The single declaration of which tools this server exposes.

Each entry is a `@tool`-decorated function (annotations live on the function).
`create_app` registers from this list via `mcp.add_tool`.
"""

from collections.abc import Awaitable, Callable

from backstop_mcp.server.tools.get_accounts_for_party import get_accounts_for_party
from backstop_mcp.server.tools.get_activity_detail import get_activity_detail
from backstop_mcp.server.tools.get_activity_history import get_activity_history
from backstop_mcp.server.tools.get_opportunities import get_opportunities
from backstop_mcp.server.tools.get_organization import get_organization
from backstop_mcp.server.tools.get_person import get_person
from backstop_mcp.server.tools.get_product_positions import get_product_positions
from backstop_mcp.server.tools.list_custom_fields import list_custom_fields
from backstop_mcp.server.tools.system_info import get_system_info

type ToolFunction = Callable[..., Awaitable[object]]

TOOLS: tuple[ToolFunction, ...] = (
    get_system_info,
    get_organization,
    get_person,
    list_custom_fields,
    get_activity_history,
    get_activity_detail,
    get_opportunities,
    get_product_positions,
    get_accounts_for_party,
)
