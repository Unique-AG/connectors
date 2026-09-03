import logging
from datetime import timedelta
from typing import Self

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.caching import CachedValue, CacheFreshness
from backstop_mcp.features.activity_tags.api_responses import ActivityTagAttributes
from backstop_mcp.features.activity_tags.internal_dto import ActivityTagDto

logger = logging.getLogger(__name__)


async def _fetch_activity_tags(client: BackstopClient) -> dict[str, ActivityTagDto]:
    """Fetch Backstop's activity-tag catalog in one paginated walk, keyed by tag id."""
    page = await client.paginate(
        "/activity-tags",
        schema=BackstopApiResource[ActivityTagAttributes],
        max_records=None,
        page_size=1000,
    )

    tags_by_id: dict[str, ActivityTagDto] = {}
    for resource in page.items:
        tag = ActivityTagDto.from_resource(resource)
        if tag is None:
            continue
        existing = tags_by_id.get(tag.id)
        if existing is None:
            tags_by_id[tag.id] = tag
        elif existing != tag:
            logger.warning(
                "Conflicting activity tags for duplicate id %r; retaining first tag", tag.id
            )
    return tags_by_id


class ActivityTagsService:
    """Process-wide activity-tag catalog.

    Tags come from a real Backstop fetch and live in one in-memory dict keyed by tag id.
    Until a fetch succeeds this service has nothing to serve. Constructed by
    `get_activity_tags_service` in this feature's `dependencies.py`.

    The TTL, single-flight and serve-stale protocol behind `get` is the composed `CachedValue`.
    """

    def __init__(
        self, *, client: BackstopClient, ttl: timedelta, caching_enabled: bool = True
    ) -> None:
        self._client: BackstopClient = client
        self._cache: CachedValue[dict[str, ActivityTagDto]] = CachedValue(
            ttl=ttl,
            snapshot=dict,
            name="activity-tag",
            log_prefix="activity_tags",
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
    ) -> tuple[dict[str, ActivityTagDto], CacheFreshness]:
        return await self._cache.get(lambda: _fetch_activity_tags(self._client), refresh=refresh)
