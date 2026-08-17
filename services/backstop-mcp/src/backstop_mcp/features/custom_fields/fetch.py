from collections.abc import Mapping
from typing import cast

from backstop_mcp.backstop_client import BackstopApiResource, BackstopClient
from backstop_mcp.features.custom_fields.entity_types import custom_field_entity_type_from_bean
from backstop_mcp.features.custom_fields.types import (
    CustomFieldDefinition,
    CustomFieldDefinitionAttributes,
)

_DEFINITIONS_PATH = "/custom-field-definitions"
_DEFINITIONS_PAGE_SIZE = 1000
_ENTRY_COLLECTION_KEYS = ("entries", "lovEntries", "viewableEntries", "options", "values")

type DefinitionResource = BackstopApiResource[CustomFieldDefinitionAttributes]


def _select_options(value: object | None) -> list[object]:
    """Keep a list of inline picklist options, including object-shaped collections."""
    if isinstance(value, list):
        return list(cast(list[object], value))
    if not isinstance(value, Mapping):
        return []
    payload = cast(Mapping[str, object], value)
    for key in _ENTRY_COLLECTION_KEYS:
        items = payload.get(key)
        if isinstance(items, list) and items:
            return list(cast(list[object], items))
    raw_select = payload.get("selectOptions")
    if isinstance(raw_select, list) and raw_select:
        return list(cast(list[object], raw_select))
    raw_data = payload.get("data")
    if isinstance(raw_data, list):
        return list(cast(list[object], raw_data))
    if isinstance(raw_data, Mapping):
        return [dict(cast(Mapping[str, object], raw_data))]
    return []


def definition_from_resource(resource: DefinitionResource) -> CustomFieldDefinition | None:
    """Map one CRM definition resource onto Backstop attributes.

    Returns None when `name` or `entityType` is missing, or `entityType` is not one of the
    six known Beans.
    """
    attrs = resource.attributes
    name = attrs.name
    if not name:
        return None

    entity_type = attrs.entity_type
    if not entity_type or custom_field_entity_type_from_bean(entity_type) is None:
        return None

    return CustomFieldDefinition(
        id=resource.id,
        name=name,
        entity_type=entity_type,
        field_type=attrs.field_type,
        field_type_display=attrs.field_type_display,
        is_time_series=bool(attrs.is_time_series),
        select_options=_select_options(attrs.select_options),
        tab_name=attrs.tab_name,
        group_name=attrs.group_name,
        layout_name=attrs.layout_name,
        resource_type=attrs.resource_type,
        required=attrs.required,
        client_required=attrs.client_required,
        system_defined=attrs.system_defined,
        description=attrs.description,
    )


async def fetch_custom_field_definitions(client: BackstopClient) -> list[CustomFieldDefinition]:
    """Fetch the instance's full custom-field schema in one paginated walk."""
    page = await client.paginate(
        _DEFINITIONS_PATH,
        schema=BackstopApiResource[CustomFieldDefinitionAttributes],
        max_records=None,
        page_size=_DEFINITIONS_PAGE_SIZE,
    )

    definitions: list[CustomFieldDefinition] = []
    for resource in page.items:
        definition = definition_from_resource(resource)
        if definition is not None:
            definitions.append(definition)
    return definitions
