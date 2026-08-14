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

    id: str
    name: str
    entity_type: str
    field_type: str | None = None
    field_type_display: str | None = None
    is_time_series: bool = False
    select_options: list[object] = Field(default_factory=list)
    tab_name: str | None = None
    group_name: str | None = None
    layout_name: str | None = None
    resource_type: str | None = None
    required: bool | None = None
    client_required: bool | None = None
    system_defined: bool | None = None
    description: str | None = None
