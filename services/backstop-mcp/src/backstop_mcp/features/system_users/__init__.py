"""Cached Backstop system-user catalog.

`userName` is the login `search_opportunities` filters on; `disabled` flags a departed
colleague so a name lookup does not silently return an empty pipeline.
`SystemUsersService` is the TTL-cached instance catalog; `list_system_users` publishes it.
`get_current_caller_system_user` reads the snapshot stored on the credential at login.
"""

from backstop_mcp.features.system_users.api_responses import SystemUserAttributes
from backstop_mcp.features.system_users.dependencies import (
    get_current_caller_system_user,
    get_system_users_service,
)
from backstop_mcp.features.system_users.internal_dto import SystemUserDto
from backstop_mcp.features.system_users.responses import ListSystemUsersResponse
from backstop_mcp.features.system_users.system_users_service import (
    SystemUsersService,
    find_system_user_by_user_name,
    system_user_relationship,
)

__all__ = [
    "ListSystemUsersResponse",
    "SystemUserAttributes",
    "SystemUserDto",
    "SystemUsersService",
    "find_system_user_by_user_name",
    "get_current_caller_system_user",
    "get_system_users_service",
    "system_user_relationship",
]
