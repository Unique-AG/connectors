from typing import Annotated, Literal

from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from backstop_mcp.features.custom_fields import (
    CustomFieldDefinition,
    CustomFieldEntityType,
    custom_field_entity_type_from_bean,
)
from backstop_mcp.server.runtime import get_backstop_client, get_custom_fields_service


class ListCustomFieldsResponse(BaseModel):
    """Custom-field definitions grouped by the requested entity types."""

    status: Literal["ok"] = Field(default="ok", description="Always 'ok'.")
    cache: Literal["ok", "stale"] = Field(
        description=(
            "'ok' when the catalog was fetched this call or is still fresh; 'stale' when a "
            "previous catalog is served because refresh failed."
        )
    )
    definitions_by_entity: dict[CustomFieldEntityType, list[CustomFieldDefinition]] = Field(
        description=(
            "Custom-field definitions keyed by the requested entity type. An entity with "
            "none on file is still present with an empty list."
        )
    )


def _definitions_for(
    catalog: list[CustomFieldDefinition], entity_type: CustomFieldEntityType
) -> list[CustomFieldDefinition]:
    return [
        definition
        for definition in catalog
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
                "Backstop entity types whose custom-field definitions to list: "
                "organizations, people, accounts, opportunities, products, or party."
            ),
        ),
    ],
    refresh: Annotated[
        bool,
        Field(description="Do not pass true unless the user reports a missing field."),
    ] = False,
) -> ListCustomFieldsResponse:
    """List custom-field definitions for the requested Backstop entity types.

    Use when you need the custom-field catalog (ids, types, layout, select options)
    for one or more of organizations, people, accounts, opportunities, products, or party.
    Pass refresh=true only when the user reports a missing field.
    """
    client = await get_backstop_client()
    service = get_custom_fields_service()
    catalog, cache = await service.get(client, refresh=refresh)
    return ListCustomFieldsResponse(
        cache=cache,
        definitions_by_entity={
            requested: _definitions_for(catalog, requested) for requested in entity_types
        },
    )
