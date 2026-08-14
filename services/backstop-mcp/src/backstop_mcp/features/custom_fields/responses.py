"""Custom-field-shaped views of the shared resolution responses (`resolution.py`).

The counterpart to `party_resolver/responses.py`, and here for the same reason: these are the
feature's own wire vocabulary, so every tool that resolves a field returns the same shapes.
They lived next to tool handlers until multiple tools needed them and had to share shapes.
"""

from typing import ClassVar

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


class CustomFieldDefinitionResponse(BaseModel):
    """A resolved field definition, returned so a wrong resolution is visible rather than silent."""

    model_config: ClassVar[ConfigDict] = ConfigDict(from_attributes=True)

    id: str
    name: str
    entity_type: str
    field_type: str | None = None
    field_type_display: str | None = None
    is_time_series: bool
    select_options: list[object] = Field(default_factory=list)
    tab_name: str | None = None
    group_name: str | None = None
    layout_name: str | None = None
    resource_type: str | None = None
    required: bool | None = None
    client_required: bool | None = None
    system_defined: bool | None = None
    description: str | None = None


class FieldCandidateResponse(CandidateResponse):
    """One ambiguous field match, returned so the model can ask the user to pick one."""

    id: str
    name: str
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
        id=definition.id,
        name=definition.name,
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
    "CustomFieldDefinitionResponse",
    "FieldAmbiguousResponse",
    "FieldCandidateResponse",
    "definition_response",
    "field_candidate_response",
    "unresolved_field_response",
]
