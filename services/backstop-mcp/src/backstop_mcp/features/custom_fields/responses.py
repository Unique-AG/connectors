"""Custom-field-shaped views of the shared resolution responses (`resolution.py`).

The counterpart to `party_resolver/responses.py`, and here for the same reason: these are the
feature's own wire vocabulary, so every tool that resolves a field returns the same shapes.
They lived next to tool handlers until multiple tools needed them and had to share shapes.
"""

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.features.custom_fields.index import FieldCandidate
from backstop_mcp.features.custom_fields.types import CustomFieldDefinition
from backstop_mcp.features.resolution import (
    AmbiguousResponse,
    CandidateResponse,
    NotFoundResponse,
    Unresolved,
    unresolved_response,
)


class AllowedValueResponse(BaseModel):
    """One picklist option, returned so a caller can validate a write before attempting it."""

    model_config = ConfigDict(from_attributes=True)

    id: str | None = None
    label: str


class CustomFieldDefinitionResponse(BaseModel):
    """A resolved field definition, returned so a wrong resolution is visible rather than silent."""

    model_config = ConfigDict(from_attributes=True)

    definition_id: str
    entity_type: str
    crm_name: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    field_type: str | None = None
    field_type_display: str | None = None
    is_time_series: bool
    allowed_values: list[AllowedValueResponse] = Field(default_factory=list)


class FieldCandidateResponse(CandidateResponse):
    """One ambiguous field match, returned so the model can ask the user to pick one."""

    definition_id: str
    display_name: str
    crm_name: str
    entity_type: str


# Concrete parameterization of the shared model. A plain assignment, not a subclass: pydantic
# resolves the subscript to a real model class, which is what FastMCP needs for output schemas.
FieldAmbiguousResponse = AmbiguousResponse[FieldCandidateResponse]


def definition_response(definition: CustomFieldDefinition) -> CustomFieldDefinitionResponse:
    return CustomFieldDefinitionResponse.model_validate(definition)


def field_candidate_response(candidate: FieldCandidate) -> FieldCandidateResponse:
    definition = candidate.value
    return FieldCandidateResponse(
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
        to_candidate=field_candidate_response,
    )


__all__ = [
    "AllowedValueResponse",
    "CustomFieldDefinitionResponse",
    "FieldAmbiguousResponse",
    "FieldCandidateResponse",
    "definition_response",
    "field_candidate_response",
    "unresolved_field_response",
]
