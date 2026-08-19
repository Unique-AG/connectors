from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from backstop_mcp.lenient import LenientBool

__all__ = ["CustomFieldDefinitionAttributes"]

_StrippedStr = Annotated[str, StringConstraints(strip_whitespace=True)]


class CustomFieldDefinitionAttributes(BaseModel):
    """Wire shape for `custom-field-definitions` attributes (subset we need)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: _StrippedStr | None = None
    entity_type: _StrippedStr | None = Field(default=None, alias="entityType")
    field_type: _StrippedStr | None = Field(default=None, alias="fieldType")
    field_type_display: _StrippedStr | None = Field(default=None, alias="fieldTypeDisplay")
    is_time_series: LenientBool = Field(default=None, alias="isTimeSeries")
    select_options: object | None = Field(default=None, alias="selectOptions")
    tab_name: _StrippedStr | None = Field(default=None, alias="tabName")
    group_name: _StrippedStr | None = Field(default=None, alias="groupName")
    layout_name: _StrippedStr | None = Field(default=None, alias="layoutName")
    resource_type: _StrippedStr | None = Field(default=None, alias="resourceType")
    description: _StrippedStr | None = None
    required: LenientBool = None
    client_required: LenientBool = Field(default=None, alias="clientRequired")
    system_defined: LenientBool = Field(default=None, alias="systemDefined")
