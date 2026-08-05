from typing import Literal

from fastmcp import Context
from pydantic import BaseModel, Field

from backstop_mcp.custom_fields import CustomFieldDefinition, normalize_entity_type
from backstop_mcp.resolution import (
    AmbiguousResponse,
    Candidate,
    CandidateEcho,
    NotFoundResponse,
    Resolved,
    Unresolved,
    unresolved_response,
)
from backstop_mcp.runtime import get_backstop_client, get_custom_fields_service


class AllowedValueEcho(BaseModel):
    id: str | None = None
    label: str


class CustomFieldDefinitionEcho(BaseModel):
    definition_id: str
    entity_type: str
    crm_name: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    field_type: str | None = None
    field_type_display: str | None = None
    is_time_series: bool
    allowed_values: list[AllowedValueEcho] = Field(default_factory=list)


class FieldCandidateEcho(CandidateEcho):
    definition_id: str
    display_name: str
    crm_name: str
    entity_type: str


# Concrete parameterization of the shared model — see `resolution.AmbiguousResponse`.
FieldAmbiguousResponse = AmbiguousResponse[FieldCandidateEcho]


class ResolveCustomFieldResolvedResponse(BaseModel):
    status: Literal["resolved"] = "resolved"
    definition: CustomFieldDefinitionEcho


type ResolveCustomFieldResponse = (
    ResolveCustomFieldResolvedResponse | FieldAmbiguousResponse | NotFoundResponse
)


def definition_echo(definition: CustomFieldDefinition) -> CustomFieldDefinitionEcho:
    return CustomFieldDefinitionEcho(
        definition_id=definition.definition_id,
        entity_type=definition.entity_type,
        crm_name=definition.crm_name,
        display_name=definition.display_name,
        aliases=list(definition.aliases),
        description=definition.description,
        field_type=definition.field_type,
        field_type_display=definition.field_type_display,
        is_time_series=definition.is_time_series,
        allowed_values=[
            AllowedValueEcho(id=v.id, label=v.label) for v in definition.allowed_values
        ],
    )


def field_candidate_echo(candidate: Candidate[CustomFieldDefinition]) -> FieldCandidateEcho:
    definition = candidate.value
    return FieldCandidateEcho(
        key=candidate.key,
        label=candidate.label,
        definition_id=definition.definition_id,
        display_name=definition.display_name,
        crm_name=definition.crm_name,
        entity_type=definition.entity_type,
    )


def unresolved_field_response(
    result: Unresolved[CustomFieldDefinition],
) -> FieldAmbiguousResponse | NotFoundResponse:
    return unresolved_response(
        result,
        ambiguous_model=FieldAmbiguousResponse,
        to_echo=field_candidate_echo,
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
    result = await get_custom_fields_service().resolve(
        entity_type=entity,
        query=query,
        client=client,
        refresh=refresh,
        ctx=ctx,
    )

    if isinstance(result, Resolved):
        return ResolveCustomFieldResolvedResponse(definition=definition_echo(result.value))
    return unresolved_field_response(result)
