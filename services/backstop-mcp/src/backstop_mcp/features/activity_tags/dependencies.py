from functools import lru_cache

from backstop_mcp.dependencies import get_backstop_config
from backstop_mcp.features.activity_tags.activity_tags_service import ActivityTagsService


@lru_cache(maxsize=1)
def get_activity_tags_service() -> ActivityTagsService:
    return ActivityTagsService.with_ttl_minutes(
        ttl_minutes=get_backstop_config().activity_tag_ttl_minutes,
    )
