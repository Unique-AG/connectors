from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

_StrippedStr = Annotated[str, StringConstraints(strip_whitespace=True)]


class CustomFieldDefinitionAttributes(BaseModel):
    """Wire shape for `custom-field-definitions` attributes (subset we need)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: _StrippedStr | None = None
    entity_type: _StrippedStr | None = Field(default=None, alias="entityType")
    field_type: _StrippedStr | None = Field(default=None, alias="fieldType")
    field_type_display: _StrippedStr | None = Field(default=None, alias="fieldTypeDisplay")
    is_time_series: bool | None = Field(default=None, alias="isTimeSeries")
    select_options: object | None = Field(default=None, alias="selectOptions")
    tab_name: _StrippedStr | None = Field(default=None, alias="tabName")
    group_name: _StrippedStr | None = Field(default=None, alias="groupName")
    layout_name: _StrippedStr | None = Field(default=None, alias="layoutName")
    resource_type: _StrippedStr | None = Field(default=None, alias="resourceType")
    description: _StrippedStr | None = None
    required: bool | None = None
    client_required: bool | None = Field(default=None, alias="clientRequired")
    system_defined: bool | None = Field(default=None, alias="systemDefined")


class CustomFieldDefinition(BaseModel):
    """A CRM custom-field definition from Backstop attributes."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str = Field(description="Backstop id of this custom-field definition.")
    name: str = Field(description="Field name as it appears on a record.")
    entity_type: str = Field(
        description=(
            "Backstop bean this field belongs to (e.g. 'Organization', 'Person'). The "
            "response groups definitions under the MCP entity-type key instead."
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
        default=None, description="Backstop layout group this field sits in, when published."
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
        default=None, description="Whether this instance marks this field as client-required."
    )
    system_defined: bool | None = Field(
        default=None,
        description="True when this is a Backstop-defined field, not tenant-defined.",
    )
    description: str | None = Field(
        default=None, description="Help text on the definition, when Backstop publishes one."
    )
