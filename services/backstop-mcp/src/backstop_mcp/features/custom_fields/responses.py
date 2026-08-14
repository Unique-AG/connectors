from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.features.custom_fields.types import CustomFieldDefinition


class CustomFieldDefinitionResponse(BaseModel):
    """A field definition, returned so a wrong catalog row is visible rather than silent."""

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


def definition_response(definition: CustomFieldDefinition) -> CustomFieldDefinitionResponse:
    return CustomFieldDefinitionResponse.model_validate(definition)


__all__ = [
    "CustomFieldDefinitionResponse",
    "definition_response",
]
