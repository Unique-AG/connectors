import logging

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.custom_fields.api_responses import CustomFieldDefinitionAttributes
from backstop_mcp.features.custom_fields.internal_dto import CustomFieldDefinitionDto

logger = logging.getLogger(__name__)

_DEFINITIONS_PATH = "/custom-field-definitions"
_DEFINITIONS_PAGE_SIZE = 1000
_DUPLICATE_DEFINITION_WARNING = (
    "Conflicting custom-field definitions for duplicate id %r; retaining first definition"
)


async def fetch_custom_field_definitions(
    client: BackstopClient,
) -> dict[str, CustomFieldDefinitionDto]:
    """Fetch Backstop's full custom-field schema in one paginated walk, keyed by definition id."""
    page = await client.paginate(
        _DEFINITIONS_PATH,
        schema=BackstopApiResource[CustomFieldDefinitionAttributes],
        max_records=None,
        page_size=_DEFINITIONS_PAGE_SIZE,
    )

    definitions_by_id: dict[str, CustomFieldDefinitionDto] = {}
    for resource in page.items:
        definition = CustomFieldDefinitionDto.from_resource(resource)
        if definition is None:
            continue
        existing = definitions_by_id.get(definition.id)
        if existing is None:
            definitions_by_id[definition.id] = definition
        elif existing != definition:
            logger.warning(_DUPLICATE_DEFINITION_WARNING, definition.id)
    return definitions_by_id
