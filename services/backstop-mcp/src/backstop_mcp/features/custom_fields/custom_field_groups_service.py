import logging
from datetime import timedelta
from typing import Self

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.caching import CachedValue, CacheFreshness
from backstop_mcp.features.custom_fields.api_responses import CustomFieldGroupAttributes
from backstop_mcp.features.custom_fields.internal_dto import CustomFieldGroupDto

logger = logging.getLogger(__name__)


async def _fetch_custom_field_groups(client: BackstopClient) -> dict[str, CustomFieldGroupDto]:
    """Fetch Backstop's layout-group catalog in one paginated walk, keyed by group id."""
    page = await client.paginate(
        "/custom-field-groups",
        schema=BackstopApiResource[CustomFieldGroupAttributes],
        max_records=None,
        page_size=1000,
    )

    groups_by_id: dict[str, CustomFieldGroupDto] = {}
    for resource in page.items:
        group = CustomFieldGroupDto.from_resource(resource)
        if group is None:
            continue
        existing = groups_by_id.get(group.id)
        if existing is None:
            groups_by_id[group.id] = group
        elif existing != group:
            logger.warning(
                "Conflicting custom-field groups for duplicate id %r; retaining first group",
                group.id,
            )
    return groups_by_id


class CustomFieldGroupsService:
    """Process-wide custom-field group catalog.

    Groups come from a real Backstop fetch and live in one in-memory dict keyed by group id.
    Until a fetch succeeds this service has nothing to serve. Constructed by
    `get_custom_field_groups_service` in this feature's `dependencies.py`.

    The TTL, single-flight and serve-stale protocol behind `get` is the composed `CachedValue`.
    """

    def __init__(
        self, *, client: BackstopClient, ttl: timedelta, caching_enabled: bool = True
    ) -> None:
        self._client: BackstopClient = client
        self._cache: CachedValue[dict[str, CustomFieldGroupDto]] = CachedValue(
            ttl=ttl,
            snapshot=dict,
            name="custom-field group",
            log_prefix="custom_fields.groups",
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
    ) -> tuple[dict[str, CustomFieldGroupDto], CacheFreshness]:
        return await self._cache.get(
            lambda: _fetch_custom_field_groups(self._client), refresh=refresh
        )
