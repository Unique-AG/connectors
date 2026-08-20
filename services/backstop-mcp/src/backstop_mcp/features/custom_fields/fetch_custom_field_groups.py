import logging

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.custom_fields.api_responses import CustomFieldGroupAttributes
from backstop_mcp.features.custom_fields.internal_dto import CustomFieldGroupDto

logger = logging.getLogger(__name__)

_GROUPS_PATH = "/custom-field-groups"
_GROUPS_PAGE_SIZE = 1000
_DUPLICATE_GROUP_WARNING = (
    "Conflicting custom-field groups for duplicate id %r; retaining first group"
)


async def fetch_custom_field_groups(client: BackstopClient) -> dict[str, CustomFieldGroupDto]:
    """Fetch Backstop's layout-group catalog in one paginated walk, keyed by group id."""
    page = await client.paginate(
        _GROUPS_PATH,
        schema=BackstopApiResource[CustomFieldGroupAttributes],
        max_records=None,
        page_size=_GROUPS_PAGE_SIZE,
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
            logger.warning(_DUPLICATE_GROUP_WARNING, group.id)
    return groups_by_id
