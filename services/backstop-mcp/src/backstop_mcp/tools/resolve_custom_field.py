from typing import Literal

from pydantic import BaseModel, Field

from backstop_mcp.backstop_client import get_backstop_client
from backstop_mcp.custom_fields import (
    CustomFieldDefinition,
    FieldAmbiguous,
    FieldNotFound,
    FieldResolved,
    get_custom_fields_service,
)
from backstop_mcp.custom_fields.overrides import normalize_entity_type


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


class FieldCandidateEcho(BaseModel):
    definition_id: str
    display_name: str
    crm_name: str
    entity_type: str
    label: str


class ResolveCustomFieldResolvedResponse(BaseModel):
    status: Literal["resolved"] = "resolved"
    definition: CustomFieldDefinitionEcho


class ResolveCustomFieldAmbiguousResponse(BaseModel):
    status: Literal["ambiguous"] = "ambiguous"
    query: str
    entity_type: str
    candidates: list[FieldCandidateEcho]


class ResolveCustomFieldNotFoundResponse(BaseModel):
    status: Literal["not_found"] = "not_found"
    query: str
    entity_type: str


type ResolveCustomFieldResponse = (
    ResolveCustomFieldResolvedResponse
    | ResolveCustomFieldAmbiguousResponse
    | ResolveCustomFieldNotFoundResponse
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


async def resolve_custom_field(
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
    async with await get_backstop_client() as client:
        result = await get_custom_fields_service().resolve(
            entity_type=entity,
            query=query,
            client=client,
            refresh=refresh,
        )

    if isinstance(result, FieldResolved):
        return ResolveCustomFieldResolvedResponse(definition=definition_echo(result.definition))
    if isinstance(result, FieldAmbiguous):
        return ResolveCustomFieldAmbiguousResponse(
            query=result.query,
            entity_type=result.entity_type,
            candidates=[
                FieldCandidateEcho(
                    definition_id=c.definition_id,
                    display_name=c.display_name,
                    crm_name=c.crm_name,
                    entity_type=c.entity_type,
                    label=c.label,
                )
                for c in result.candidates
            ],
        )
    assert isinstance(result, FieldNotFound)
    return ResolveCustomFieldNotFoundResponse(query=result.query, entity_type=result.entity_type)
