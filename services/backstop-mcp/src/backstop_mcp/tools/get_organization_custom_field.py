from typing import Literal

from fastmcp import Context
from pydantic import BaseModel

from backstop_mcp.custom_fields import read_custom_field_value
from backstop_mcp.party_resolver import (
    PartyAmbiguousResponse,
    ResolvedPartyEcho,
    party_echo,
    resolve_party,
    unresolved_party_response,
)
from backstop_mcp.resolution import NotFoundResponse, Resolved
from backstop_mcp.runtime import get_backstop_client, get_custom_fields_service
from backstop_mcp.tools.resolve_custom_field import (
    CustomFieldDefinitionEcho,
    FieldAmbiguousResponse,
    definition_echo,
    unresolved_field_response,
)


class OrganizationCustomFieldResolvedResponse(BaseModel):
    status: Literal["resolved"] = "resolved"
    value: object | None = None
    definition: CustomFieldDefinitionEcho
    resolved: ResolvedPartyEcho


type GetOrganizationCustomFieldResponse = (
    PartyAmbiguousResponse
    | FieldAmbiguousResponse
    | NotFoundResponse
    | OrganizationCustomFieldResolvedResponse
)


async def get_organization_custom_field(
    ctx: Context,
    field: str,
    party_id: str | None = None,
    search: str | None = None,
) -> GetOrganizationCustomFieldResponse:
    """Read one organization custom field by name (e.g. Investor Status) without hardcoded IDs.

    Resolve the organization with party_id or search (never invent party_id), then resolve
    the custom field by human name/alias against the live instance schema and read its value
    via the correct regular or time-series path.
    Exactly one of party_id or search must be provided.
    """
    client = await get_backstop_client()

    # `confirm_name=True`: unlike `get_organization` this tool never fetches the whole record,
    # so on the trusted-`party_id` path there would otherwise be no name to echo — and the echo
    # is what makes a wrong id visible rather than silent.
    party_result = await resolve_party(
        ctx,
        client,
        search_type="organizations",
        party_id=party_id,
        search=search,
        confirm_name=True,
    )
    if not isinstance(party_result, Resolved):
        return unresolved_party_response(party_result)

    field_result = await get_custom_fields_service().resolve(
        entity_type="organizations",
        query=field,
        client=client,
        ctx=ctx,
    )
    if not isinstance(field_result, Resolved):
        return unresolved_field_response(field_result)

    party = party_result.value
    value = await read_custom_field_value(
        client,
        entity_type="organizations",
        entity_id=party.id,
        definition=field_result.value,
    )

    return OrganizationCustomFieldResolvedResponse(
        value=value,
        definition=definition_echo(field_result.value),
        resolved=party_echo(party),
    )
