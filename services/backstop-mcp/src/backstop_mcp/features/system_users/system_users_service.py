import logging
from datetime import timedelta
from typing import Self

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.caching import CachedValue, CacheFreshness
from backstop_mcp.features.system_users.api_responses import SystemUserAttributes
from backstop_mcp.features.system_users.internal_dto import SystemUserDto

logger = logging.getLogger(__name__)


async def _fetch_system_users(client: BackstopClient) -> dict[str, SystemUserDto]:
    """Fetch Backstop's system-user catalog in one paginated walk, keyed by user id.

    The collection does not accept a search or `filter[name][like]`. This walk is the whole
    roster so `SystemUsersService` can cache it and tools can filter users in memory instead
    of returning every colleague on each lookup.
    """
    page = await client.paginate(
        "/system-users",
        schema=BackstopApiResource[SystemUserAttributes],
        max_records=None,
        page_size=200,
    )

    users_by_id: dict[str, SystemUserDto] = {}
    for resource in page.items:
        user = SystemUserDto.from_resource(resource)
        if user is None:
            continue
        existing = users_by_id.get(user.id)
        if existing is None:
            users_by_id[user.id] = user
        elif existing != user:
            logger.warning(
                "Conflicting system users for duplicate id %r; retaining first user", user.id
            )
    return users_by_id


class SystemUsersService:
    """Process-wide system-user catalog.

    Users come from a real Backstop fetch and live in one in-memory dict keyed by user id.
    `/system-users` has no search filter. A name or login lookup would otherwise dump the
    whole roster, so this service walks once, caches `{id: dto}`, and callers substring-filter
    that map in memory. Until a fetch succeeds there is nothing to serve. Constructed by
    `get_system_users_service` in this feature's `dependencies.py`.

    The TTL, single-flight and serve-stale protocol behind `get` is the composed `CachedValue`.
    """

    def __init__(
        self, *, client: BackstopClient, ttl: timedelta, caching_enabled: bool = True
    ) -> None:
        self._client: BackstopClient = client
        self._cache: CachedValue[dict[str, SystemUserDto]] = CachedValue(
            ttl=ttl,
            snapshot=dict,
            name="system-user",
            log_prefix="system_users",
            caching_enabled=caching_enabled,
        )

    @classmethod
    def with_ttl_minutes(
        cls, *, client: BackstopClient, ttl_minutes: int, caching_enabled: bool = True
    ) -> Self:
        return cls(
            client=client, ttl=timedelta(minutes=ttl_minutes), caching_enabled=caching_enabled
        )

    async def get(
        self, *, refresh: bool = False
    ) -> tuple[dict[str, SystemUserDto], CacheFreshness]:
        return await self._cache.get(lambda: _fetch_system_users(self._client), refresh=refresh)
