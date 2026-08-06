"""Custom-field-shaped views of the shared resolution responses (`resolution.py`).

The counterpart to `party_resolver/responses.py`, and here for the same reason: these are the
feature's own wire vocabulary, so every tool that resolves a field returns the same shapes.
They lived next to tool handlers until multiple tools needed them and had to share shapes.
"""

from pydantic import BaseModel, Field

from backstop_mcp.features.custom_fields.index import FieldCandidate
from backstop_mcp.features.custom_fields.types import CustomFieldDefinition
from backstop_mcp.features.resolution import (
    AmbiguousResponse,
    CandidateEcho,
    NotFoundResponse,
    Unresolved,
    unresolved_response,
)


class AllowedValueEcho(BaseModel):
    """One picklist option, echoed so a caller can validate a write before attempting it."""

    id: str | None = None
    label: str


class CustomFieldDefinitionEcho(BaseModel):
    """A resolved field definition, echoed so a wrong resolution is visible rather than silent."""

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
    """One ambiguous field match, echoed so the model can ask the user to pick one."""

    definition_id: str
    display_name: str
    crm_name: str
    entity_type: str


# Concrete parameterization of the shared model. A plain assignment, not a subclass: pydantic
# resolves the subscript to a real model class, which is what FastMCP needs for output schemas.
FieldAmbiguousResponse = AmbiguousResponse[FieldCandidateEcho]


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


def field_candidate_echo(candidate: FieldCandidate) -> FieldCandidateEcho:
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
    """Convert a non-`Resolved` field resolution into the standard tool response."""
    return unresolved_response(
        result,
        ambiguous_model=FieldAmbiguousResponse,
        to_echo=field_candidate_echo,
    )


__all__ = [
    "AllowedValueEcho",
    "CustomFieldDefinitionEcho",
    "FieldAmbiguousResponse",
    "FieldCandidateEcho",
    "definition_echo",
    "field_candidate_echo",
    "unresolved_field_response",
]
