"""The single declaration of which tools this server exposes.

Each entry is a `@tool`-decorated function (annotations live on the function).
`create_app` registers from this list via `mcp.add_tool`.
"""

from collections.abc import Awaitable, Callable

from backstop_mcp.features.accounts.tools.get_accounts_for_party import get_accounts_for_party
from backstop_mcp.features.accounts.tools.get_product_investors import get_product_investors
from backstop_mcp.features.accounts.tools.get_time_series import get_time_series
from backstop_mcp.features.activity_history.tools.get_activity_detail import get_activity_detail
from backstop_mcp.features.activity_history.tools.get_activity_history import get_activity_history
from backstop_mcp.features.activity_history.tools.search_activities import search_activities
from backstop_mcp.features.activity_tags.tools.list_activity_tags import list_activity_tags
from backstop_mcp.features.custom_fields.tools.list_custom_field_groups import (
    list_custom_field_groups,
)
from backstop_mcp.features.custom_fields.tools.list_custom_fields import list_custom_fields
from backstop_mcp.features.opportunities.tools.get_opportunities import get_opportunities
from backstop_mcp.features.opportunities.tools.search_opportunities import search_opportunities
from backstop_mcp.features.org_people.tools.get_organization import get_organization
from backstop_mcp.features.org_people.tools.get_people_for_party import get_people_for_party
from backstop_mcp.features.org_people.tools.get_person import get_person
from backstop_mcp.features.system_users.tools.list_system_users import list_system_users

type ToolFunction = Callable[..., Awaitable[object]]

TOOLS: tuple[ToolFunction, ...] = (
    get_organization,
    get_person,
    list_custom_fields,
    list_custom_field_groups,
    list_activity_tags,
    list_system_users,
    get_activity_history,
    get_activity_detail,
    search_activities,
    get_opportunities,
    search_opportunities,
    get_time_series,
    get_product_investors,
    get_accounts_for_party,
    get_people_for_party,
)
