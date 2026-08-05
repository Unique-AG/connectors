from typing import Literal

from fastmcp import Context
from pydantic import BaseModel

from backstop_mcp.features.custom_fields import (
    CustomFieldDefinitionEcho,
    FieldAmbiguousResponse,
    definition_echo,
    normalize_entity_type,
    resolve_field,
    unresolved_field_response,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved
from backstop_mcp.server.runtime import get_backstop_client, get_custom_fields_service


class ResolveCustomFieldResolvedResponse(BaseModel):
    status: Literal["resolved"] = "resolved"
    definition: CustomFieldDefinitionEcho


type ResolveCustomFieldResponse = (
    ResolveCustomFieldResolvedResponse | FieldAmbiguousResponse | NotFoundResponse
)


async def resolve_custom_field(
    ctx: Context,
    entity_type: str,
    query: str,
    refresh: bool = False,
) -> ResolveCustomFieldResponse:
    """Resolve a Backstop custom field by human name or alias for one entity type.

    Use when the glossary on other tools is missing, truncated, or the user's phrase is
    ambiguous. Pass refresh=true to re-fetch definitions from Backstop into the cache.
    entity_type is an API resource name such as organizations, contacts, people.
    """
    entity = normalize_entity_type(entity_type)
    client = await get_backstop_client()
    result = await resolve_field(
        get_custom_fields_service(),
        client,
        entity_type=entity,
        query=query,
        refresh=refresh,
        ctx=ctx,
    )

    if isinstance(result, Resolved):
        return ResolveCustomFieldResolvedResponse(definition=definition_echo(result.value))
    return unresolved_field_response(result)
