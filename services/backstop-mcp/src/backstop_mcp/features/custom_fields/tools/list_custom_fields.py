from collections.abc import Mapping
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.custom_fields import (
    CustomFieldDefinitionDto,
    CustomFieldDefinitionResponse,
    CustomFieldEntityType,
    CustomFieldsService,
    ListCustomFieldsResponse,
    custom_field_entity_type_from_bean,
    get_custom_fields_service,
)


def _matches(definition: CustomFieldDefinitionDto, needle: str | None) -> bool:
    """Whether `needle` is in the name, tab, group, layout, or an option, any case."""
    if needle is None:
        return True
    haystacks = (
        definition.name,
        definition.tab_name,
        definition.group_name,
        definition.layout_name,
        *(str(option) for option in definition.select_options),
    )
    return any(needle in (haystack or "").casefold() for haystack in haystacks)


def _definitions_for(
    catalog: Mapping[str, CustomFieldDefinitionDto],
    entity_type: CustomFieldEntityType,
    *,
    needle: str | None,
) -> list[CustomFieldDefinitionResponse]:
    return [
        CustomFieldDefinitionResponse.from_definition(definition)
        for definition in catalog.values()
        if custom_field_entity_type_from_bean(definition.entity_type) == entity_type
        and _matches(definition, needle)
    ]


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
)
async def list_custom_fields(
    entity_types: Annotated[
        list[CustomFieldEntityType],
        Field(
            min_length=1,
            description=(
                "Required. Standard Backstop entity types whose custom-field definitions to "
                "list: organizations, people, accounts, opportunities, products, or party. "
                "`party` is fields shared by people and organizations (PartyBean); "
                "`organizations` or `people` alone misses them."
            ),
        ),
    ],
    search: Annotated[
        str | None,
        Field(
            description=(
                "Case-insensitive substring of the field name, its tab, group, or layout, or "
                "one of its options. A tenant can hold thousands of fields: pass the user's "
                "term ('GVS', 'imminent', 'grade'), and a shorter part of it when nothing "
                "matches. Omit to list every field of those types."
            ),
        ),
    ] = None,
    refresh: Annotated[
        bool,
        Field(description="Do not pass true unless the user reports a missing field."),
    ] = False,
    custom_fields: CustomFieldsService = Depends(get_custom_fields_service),
) -> ListCustomFieldsResponse:
    """List custom-field definitions for the requested standard Backstop entity types.

    Use when you need the standard Backstop custom-field catalog (ids, types, layout, groups,
    group_id, select options) for one or more of organizations, people, accounts, opportunities,
    products, or party. Definitions may belong to a party or a concrete Backstop entity resource.
    A definition's group_id identifies its Backstop layout group when available.
    Pass refresh=true only when the user reports a missing field.

    Several fields can share a name ('Registered', 'Attended'): the tab and group say which
    one the user means (an event's fields sit in a group named for the event).

    Call like: {"entity_types": ["people", "party"], "search": "<the user's term>"}
    """
    catalog, cache = await custom_fields.get(refresh=refresh)
    needle = search.strip().casefold() if search and search.strip() else None
    return ListCustomFieldsResponse(
        cache=cache,
        definitions_by_entity={
            requested: _definitions_for(catalog, requested, needle=needle)
            for requested in entity_types
        },
    )
