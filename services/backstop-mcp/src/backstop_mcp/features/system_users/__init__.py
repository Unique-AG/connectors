"""Cached Backstop system-user catalog.

`userName` is the login `search_opportunities` filters on; `disabled` flags a departed
colleague so a name lookup does not silently return an empty pipeline.
`SystemUsersService` is the TTL-cached instance catalog; `list_system_users` publishes it.
"""

from backstop_mcp.features.system_users.api_responses import SystemUserAttributes
from backstop_mcp.features.system_users.dependencies import get_system_users_service
from backstop_mcp.features.system_users.internal_dto import SystemUserDto
from backstop_mcp.features.system_users.system_users_service import SystemUsersService

__all__ = [
    "SystemUserAttributes",
    "SystemUserDto",
    "SystemUsersService",
    "get_system_users_service",
]
