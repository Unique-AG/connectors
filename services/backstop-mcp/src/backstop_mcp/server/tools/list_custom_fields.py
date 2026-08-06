from typing import Annotated, Literal

from fastmcp.tools import tool
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import BaseModel, Field

from backstop_mcp.features.custom_fields import CustomFieldDefinitionEcho, definition_echo
from backstop_mcp.features.entity_types import EntityType
from backstop_mcp.server.runtime import get_backstop_client, get_custom_fields_service
from backstop_mcp.server.tools.results import tool_result


class ListCustomFieldsResponse(BaseModel):
    """Full custom-field catalog for one entity type."""

    status: Literal["ok"] = "ok"
    entity_type: EntityType
    count: int
    definitions: list[CustomFieldDefinitionEcho] = Field(default_factory=list)


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
)
async def list_custom_fields(
    entity_type: Annotated[
        EntityType,
        Field(
            description=(
                "Backstop entity type whose custom-field definitions to list: "
                "organizations, people, contacts, employees, opportunities, or accounts."
            ),
        ),
    ],
    refresh: Annotated[
        bool,
        Field(
            description=(
                "When true, re-fetch custom-field definitions from Backstop into the cache "
                "instead of using the cached catalog."
            ),
        ),
    ] = False,
) -> CallToolResult:
    """List custom-field definitions for one Backstop entity type.

    Use when a tool glossary is missing, truncated, or you need the full catalog (ids, types,
    aliases, allowed values) for organizations, people, contacts, employees, opportunities, or
    accounts. Pass refresh=true to re-fetch definitions from Backstop into the cache.
    """
    client = await get_backstop_client()
    service = get_custom_fields_service()
    if refresh:
        await service.refresh(client)
    else:
        await service.ensure_fresh(client)

    definitions = service.definitions_for(entity_type.value)
    return tool_result(
        ListCustomFieldsResponse(
            entity_type=entity_type,
            count=len(definitions),
            definitions=[definition_echo(definition) for definition in definitions],
        )
    )
