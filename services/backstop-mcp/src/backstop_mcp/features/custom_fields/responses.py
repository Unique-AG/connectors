"""Published custom-field catalog response models."""

from typing import ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.features.custom_fields.internal_dto import CustomFieldDefinitionDto

__all__ = ["CustomFieldDefinitionResponse"]


class CustomFieldDefinitionResponse(BaseModel):
    """One custom-field definition in the standard Backstop catalog returned to MCP callers."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str = Field(description="Backstop id of this custom-field definition.")
    name: str = Field(description="Field name as it appears on a record.")
    entity_type: str = Field(
        description=(
            "Standard Backstop Bean identifying the entity this field belongs to, such as a "
            "party or concrete Backstop entity resource."
        )
    )
    field_type: str | None = Field(
        default=None, description="Machine type of the field, as Backstop stores it."
    )
    field_type_display: str | None = Field(
        default=None, description="Human-readable type label, when Backstop publishes one."
    )
    is_time_series: bool = Field(
        default=False, description="True when this field stores a time series of values."
    )
    select_options: list[object] = Field(
        default_factory=list,
        description="Picklist options when this is a select field; empty otherwise.",
    )
    tab_name: str | None = Field(
        default=None, description="Backstop layout tab this field sits on, when published."
    )
    group_name: str | None = Field(
        default=None,
        description="Name of the Backstop layout group this field sits in, when available.",
    )
    group_id: int | None = Field(
        default=None,
        description=(
            "Backstop identifier of the layout group this field sits in, when available. "
            "Definitions with the same group_id share a layout group."
        ),
    )
    layout_name: str | None = Field(
        default=None, description="Backstop layout this field belongs to, when published."
    )
    resource_type: str | None = Field(
        default=None, description="Backstop resource type of this definition, when published."
    )
    required: bool | None = Field(
        default=None, description="Whether Backstop marks this field as required."
    )
    client_required: bool | None = Field(
        default=None, description="Whether Backstop marks this field as client-required."
    )
    system_defined: bool | None = Field(
        default=None,
        description="True when Backstop marks this field as system-defined.",
    )
    description: str | None = Field(
        default=None, description="Help text on the definition, when Backstop publishes one."
    )

    @classmethod
    def from_definition(cls, definition: CustomFieldDefinitionDto) -> Self:
        """Project an internal catalog definition onto the published response shape."""
        return cls(
            id=definition.id,
            name=definition.name,
            entity_type=definition.entity_type,
            field_type=definition.field_type,
            field_type_display=definition.field_type_display,
            is_time_series=definition.is_time_series,
            select_options=list(definition.select_options),
            tab_name=definition.tab_name,
            group_name=definition.group_name,
            group_id=definition.group_id,
            layout_name=definition.layout_name,
            resource_type=definition.resource_type,
            required=definition.required,
            client_required=definition.client_required,
            system_defined=definition.system_defined,
            description=definition.description,
        )
