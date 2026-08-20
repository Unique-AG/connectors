from typing import Annotated, Literal

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client
from backstop_mcp.features.custom_fields import (
    CustomFieldDefinitionDto,
    CustomFieldEntityType,
    CustomFieldsService,
    custom_field_entity_type_from_bean,
    get_custom_fields_service,
)


class ListCustomFieldsResponse(BaseModel):
    """Custom-field definitions grouped by the requested entity types."""

    status: Literal["ok"] = Field(default="ok", description="Always 'ok'.")
    cache: Literal["ok", "stale"] = Field(
        description=(
            "'ok' when the catalog was fetched this call or is still fresh; 'stale' when a "
            "previous catalog is served because refresh failed."
        )
    )
    definitions_by_entity: dict[CustomFieldEntityType, list[CustomFieldDefinitionDto]] = Field(
        description=(
            "Custom-field definitions keyed by the requested entity type. An entity with "
            "none on file is still present with an empty list."
        )
    )


def _definitions_for(
    catalog: list[CustomFieldDefinitionDto], entity_type: CustomFieldEntityType
) -> list[CustomFieldDefinitionDto]:
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
    client: BackstopClient = Depends(get_backstop_client),
    custom_fields: CustomFieldsService = Depends(get_custom_fields_service),
) -> ListCustomFieldsResponse:
    """List custom-field definitions for the requested Backstop entity types.

    Use when you need the custom-field catalog (ids, types, layout, select options)
    for one or more of organizations, people, accounts, opportunities, products, or party.
    Pass refresh=true only when the user reports a missing field.
    """
    catalog, cache = await custom_fields.get(client, refresh=refresh)
    return ListCustomFieldsResponse(
        cache=cache,
        definitions_by_entity={
            requested: _definitions_for(catalog, requested) for requested in entity_types
        },
    )
