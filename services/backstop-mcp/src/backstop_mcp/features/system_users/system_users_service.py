import logging
from datetime import timedelta
from typing import Self, overload

from fastmcp.exceptions import ToolError

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.caching import CachedValue, CacheFreshness
from backstop_mcp.features.system_users.api_responses import SystemUserAttributes
from backstop_mcp.features.system_users.internal_dto import SystemUserDto
from backstop_mcp.utils import identifiable_value

logger = logging.getLogger(__name__)

_SYSTEM_USER_TYPE = "system-users"


def system_user_relationship(user_id: str) -> dict[str, object]:
    """A JSON:API relationship pointing at a system user.

    Backstop takes identity pointers (`author`, `createdBy`, `assignedUser`) only as
    relationships — in `attributes` it answers `400 "author should not be in the
    'attributes' but 'relationship."`. Verified live.
    """
    return {"data": {"type": _SYSTEM_USER_TYPE, "id": user_id}}


async def _fetch_system_users(client: BackstopClient) -> dict[str, SystemUserDto]:
    """Fetch Backstop's system-user catalog in one paginated walk, keyed by casefolded login.

    The collection does not accept a search or `filter[name][like]`. This walk is the whole
    roster so `SystemUsersService` can cache it and tools can filter users in memory instead
    of returning every colleague on each lookup. A resource with no login is dropped: it
    cannot be resolved as an author or assignee.
    """
    page = await client.paginate(
        "/system-users",
        schema=BackstopApiResource[SystemUserAttributes],
        max_records=None,
        page_size=200,
    )

    users_by_login: dict[str, SystemUserDto] = {}
    for resource in page.items:
        user = SystemUserDto.from_resource(resource)
        if user is None or user.user_name is None:
            continue
        login = user.user_name.strip().casefold()
        if not login:
            continue
        existing = users_by_login.get(login)
        if existing is None:
            users_by_login[login] = user
        elif existing != user:
            logger.warning(
                "Conflicting system users for duplicate login %s; retaining first user",
                identifiable_value(login),
            )
    return users_by_login


class SystemUsersService:
    """Process-wide system-user catalog.

    Users come from a real Backstop fetch and live in one in-memory dict keyed by
    casefolded login. `/system-users` has no search filter. A name or login lookup would
    otherwise dump the whole roster, so this service walks once, caches `{login: dto}`, and
    callers substring-filter that map in memory or resolve a login exactly. Until a fetch
    succeeds there is nothing to serve. Constructed by `get_system_users_service` in this
    feature's `dependencies.py`.

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

    @overload
    async def resolve_relationship(self, username: None) -> None: ...

    @overload
    async def resolve_relationship(self, username: str) -> dict[str, object]: ...

    @overload
    async def resolve_relationship(self, username: str | None) -> dict[str, object] | None: ...

    async def resolve_relationship(self, username: str | None) -> dict[str, object] | None:
        """A `{"data": {"type": "system-users", "id"}}` relationship, or `None` if omitted."""
        if username is None:
            return None
        user = await self.resolve_by_user_name(username)
        return system_user_relationship(user.id)

    async def resolve_by_user_name(self, username: str) -> SystemUserDto:
        """The system user with this login.

        The message names the login and nothing else: this resolves a caller-supplied
        task assignee, and blaming the credential for a mistyped assignee sends the
        reader to the wrong place.
        """
        catalog, _freshness = await self.get()
        user = catalog.get(username.strip().casefold())
        if user is None:
            raise ToolError(
                f"No Backstop system user has the login {username!r}. Logins come from "
                + "list_system_users; they are not display names or party ids."
            )
        return user


async def find_system_user_by_user_name(
    client: BackstopClient, username: str
) -> SystemUserDto | None:
    """One catalog walk for the login form. `None` when the login is missing."""
    catalog = await _fetch_system_users(client)
    return catalog.get(username.strip().casefold())
