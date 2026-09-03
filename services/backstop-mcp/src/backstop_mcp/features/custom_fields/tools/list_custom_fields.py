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


def _definitions_for(
    catalog: Mapping[str, CustomFieldDefinitionDto], entity_type: CustomFieldEntityType
) -> list[CustomFieldDefinitionResponse]:
    return [
        CustomFieldDefinitionResponse.from_definition(definition)
        for definition in catalog.values()
        if custom_field_entity_type_from_bean(definition.entity_type) == entity_type
    ]


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_custom_fields(
    entity_types: Annotated[
        list[CustomFieldEntityType],
        Field(
            min_length=1,
            description=(
                "Standard Backstop entity types whose custom-field definitions to list: "
                "organizations, people, accounts, opportunities, products, or party."
            ),
        ),
    ],
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
    """
    catalog, cache = await custom_fields.get(refresh=refresh)
    return ListCustomFieldsResponse(
        cache=cache,
        definitions_by_entity={
            requested: _definitions_for(catalog, requested) for requested in entity_types
        },
    )
