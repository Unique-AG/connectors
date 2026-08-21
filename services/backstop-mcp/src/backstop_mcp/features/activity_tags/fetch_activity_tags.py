import logging

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.activity_tags.api_responses import ActivityTagAttributes
from backstop_mcp.features.activity_tags.internal_dto import ActivityTagDto

logger = logging.getLogger(__name__)

_TAGS_PATH = "/activity-tags"
_TAGS_PAGE_SIZE = 1000
_DUPLICATE_TAG_WARNING = "Conflicting activity tags for duplicate id %r; retaining first tag"


async def fetch_activity_tags(client: BackstopClient) -> dict[str, ActivityTagDto]:
    """Fetch Backstop's activity-tag catalog in one paginated walk, keyed by tag id."""
    page = await client.paginate(
        _TAGS_PATH,
        schema=BackstopApiResource[ActivityTagAttributes],
        max_records=None,
        page_size=_TAGS_PAGE_SIZE,
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
            logger.warning(_DUPLICATE_TAG_WARNING, tag.id)
    return tags_by_id
