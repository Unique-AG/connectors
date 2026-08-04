from typing import Literal

from fastmcp import Context
from pydantic import BaseModel

from backstop_mcp.backstop_client import get_backstop_client
from backstop_mcp.custom_fields import (
    FieldAmbiguous,
    FieldNotFound,
    FieldResolved,
    get_custom_fields_service,
    read_custom_field_value,
)
from backstop_mcp.party_resolver import (
    NeedsDisambiguationResponse,
    NotFoundResponse,
    Resolved,
    ResolvedPartyEcho,
    early_exit_response,
    resolve_party,
)
from backstop_mcp.tools.resolve_custom_field import (
    CustomFieldDefinitionEcho,
    FieldCandidateEcho,
    ResolveCustomFieldAmbiguousResponse,
    ResolveCustomFieldNotFoundResponse,
    definition_echo,
)


class OrganizationCustomFieldResolvedResponse(BaseModel):
    status: Literal["resolved"] = "resolved"
    value: object | None = None
    definition: CustomFieldDefinitionEcho
    resolved: ResolvedPartyEcho


type GetOrganizationCustomFieldResponse = (
    NeedsDisambiguationResponse
    | NotFoundResponse
    | ResolveCustomFieldAmbiguousResponse
    | ResolveCustomFieldNotFoundResponse
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
    async with await get_backstop_client() as client:
        party_result = await resolve_party(
            ctx,
            client,
            search_type="organizations",
            party_id=party_id,
            search=search,
        )
        if not isinstance(party_result, Resolved):
            return early_exit_response(party_result)

        field_result = await get_custom_fields_service().resolve(
            entity_type="organizations",
            query=field,
            client=client,
        )
        if isinstance(field_result, FieldAmbiguous):
            return ResolveCustomFieldAmbiguousResponse(
                query=field_result.query,
                entity_type=field_result.entity_type,
                candidates=[
                    FieldCandidateEcho(
                        definition_id=c.definition_id,
                        display_name=c.display_name,
                        crm_name=c.crm_name,
                        entity_type=c.entity_type,
                        label=c.label,
                    )
                    for c in field_result.candidates
                ],
            )
        if isinstance(field_result, FieldNotFound):
            return ResolveCustomFieldNotFoundResponse(
                query=field_result.query,
                entity_type=field_result.entity_type,
            )
        assert isinstance(field_result, FieldResolved)

        value = await read_custom_field_value(
            client,
            entity_type="organizations",
            entity_id=party_result.party.id,
            definition=field_result.definition,
        )

    party = party_result.party
    return OrganizationCustomFieldResolvedResponse(
        value=value,
        definition=definition_echo(field_result.definition),
        resolved=ResolvedPartyEcho(id=party.id, type=party.type, name=party.name),
    )
