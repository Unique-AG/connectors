from datetime import timedelta
from typing import Self

from backstop_mcp.features.activity_tags.fetch_activity_tags import fetch_activity_tags
from backstop_mcp.features.activity_tags.internal_dto import ActivityTagDto
from backstop_mcp.features.cached_catalog import CachedCatalog


class ActivityTagsService(CachedCatalog[ActivityTagDto]):
    """Process-wide activity-tag catalog.

    Tags come from a real Backstop fetch and live in one in-memory dict keyed by tag id.
    Until a fetch succeeds this service has nothing to serve. Constructed by
    `get_activity_tags_service` in this feature's `dependencies.py`.

    The TTL, single-flight and serve-stale protocol behind `get` is `CachedCatalog`.
    """

    def __init__(self, *, ttl: timedelta) -> None:
        super().__init__(
            ttl=ttl,
            fetch=fetch_activity_tags,
            log_prefix="activity_tags",
            subject="activity-tag",
        )

    @classmethod
    def with_ttl_minutes(cls, *, ttl_minutes: int) -> Self:
        return cls(ttl=timedelta(minutes=ttl_minutes))
