from datetime import timedelta
from typing import Self

from backstop_mcp.features.cached_catalog import CachedCatalog
from backstop_mcp.features.system_users.fetch_system_users import fetch_system_users
from backstop_mcp.features.system_users.internal_dto import SystemUserDto


class SystemUsersService(CachedCatalog[SystemUserDto]):
    """Process-wide system-user catalog.

    Users come from a real Backstop fetch and live in one in-memory dict keyed by user id.
    Until a fetch succeeds this service has nothing to serve. Constructed by
    `get_system_users_service` in this feature's `dependencies.py`.

    The TTL, single-flight and serve-stale protocol behind `get` is `CachedCatalog`.
    """

    def __init__(self, *, ttl: timedelta) -> None:
        super().__init__(
            ttl=ttl,
            fetch=fetch_system_users,
            log_prefix="system_users",
            subject="system-user",
        )

    @classmethod
    def with_ttl_minutes(cls, *, ttl_minutes: int) -> Self:
        return cls(ttl=timedelta(minutes=ttl_minutes))
