from functools import lru_cache

from fastmcp.dependencies import Depends

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller, get_backstop_config
from backstop_mcp.features.system_users.system_users_service import SystemUsersService


@lru_cache(maxsize=1)
def get_system_users_service(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> SystemUsersService:
    # CACHING CANDIDATE, off unless `BACKSTOP_SYSTEM_USER_CACHE_ENABLED=true`: by default every
    # read walks `/system-users`. Decide from the two histograms in `caching/cached_value.py`
    # — `catalog_get_duration_seconds_count{catalog="system-user"}` is the demand a TTL would
    # absorb, `catalog_fetch_duration_seconds{catalog="system-user"}` what one walk costs.
    config = get_backstop_config()
    return SystemUsersService.with_ttl_minutes(
        client=client,
        ttl_minutes=config.system_user_ttl_minutes,
        caching_enabled=config.system_user_cache_enabled,
    )
