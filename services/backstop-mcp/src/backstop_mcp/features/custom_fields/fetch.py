from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.custom_fields.api_responses import CustomFieldDefinitionAttributes
from backstop_mcp.features.custom_fields.internal_dto import CustomFieldDefinitionDto

_DEFINITIONS_PATH = "/custom-field-definitions"
_DEFINITIONS_PAGE_SIZE = 1000


async def fetch_custom_field_definitions(client: BackstopClient) -> list[CustomFieldDefinitionDto]:
    """Fetch the instance's full custom-field schema in one paginated walk."""
    page = await client.paginate(
        _DEFINITIONS_PATH,
        schema=BackstopApiResource[CustomFieldDefinitionAttributes],
        max_records=None,
        page_size=_DEFINITIONS_PAGE_SIZE,
    )

    definitions: list[CustomFieldDefinitionDto] = []
    for resource in page.items:
        definition = CustomFieldDefinitionDto.from_resource(resource)
        if definition is not None:
            definitions.append(definition)
    return definitions
