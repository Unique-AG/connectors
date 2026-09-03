from functools import lru_cache

from fastmcp.dependencies import Depends

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller, get_backstop_config
from backstop_mcp.features.activity_tags.activity_tags_service import ActivityTagsService


@lru_cache(maxsize=1)
def get_activity_tags_service(
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
) -> ActivityTagsService:
    # CACHING CANDIDATE, off unless `BACKSTOP_ACTIVITY_TAG_CACHE_ENABLED=true`: by default every
    # read walks `/activity-tags`. Decide from the two histograms in `caching/cached_value.py`
    # — `catalog_get_duration_seconds_count{catalog="activity-tag"}` is the demand a TTL would
    # absorb, `catalog_fetch_duration_seconds{catalog="activity-tag"}` what one walk costs.
    config = get_backstop_config()
    return ActivityTagsService.with_ttl_minutes(
        client=client,
        ttl_minutes=config.activity_tag_ttl_minutes,
        caching_enabled=config.activity_tag_cache_enabled,
    )
