from functools import lru_cache

from backstop_mcp.dependencies import get_backstop_config
from backstop_mcp.features.system_users.system_users_service import SystemUsersService


@lru_cache(maxsize=1)
def get_system_users_service() -> SystemUsersService:
    return SystemUsersService.with_ttl_minutes(
        ttl_minutes=get_backstop_config().system_user_ttl_minutes,
    )
