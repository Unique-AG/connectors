from collections.abc import Mapping
from typing import Annotated, ClassVar, cast

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

from backstop_mcp.lenient import LenientBool, LenientInt

__all__ = [
    "CustomFieldDefinitionAttributes",
    "CustomFieldGroupAttributes",
    "CustomFieldGroupParentAttributes",
]

_StrippedStr = Annotated[str, StringConstraints(strip_whitespace=True)]


def _mapping_or_none(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def _list_or_none(value: object) -> list[object] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return cast(list[object], value)
    return None


def _id_str_or_none(value: object) -> str | None:
    """JSON:API resource ids arrive as strings; Backstop also inlines them as ints."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


_IdStr = Annotated[str | None, BeforeValidator(_id_str_or_none)]


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
    group_id: LenientInt = Field(default=None, alias="groupId")
    layout_name: _StrippedStr | None = Field(default=None, alias="layoutName")
    resource_type: _StrippedStr | None = Field(default=None, alias="resourceType")
    description: _StrippedStr | None = None
    required: LenientBool = None
    client_required: LenientBool = Field(default=None, alias="clientRequired")
    system_defined: LenientBool = Field(default=None, alias="systemDefined")


class CustomFieldGroupParentAttributes(BaseModel):
    """Inline `parent` object on a `custom-field-groups` row."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    id: _IdStr = None
    name: _StrippedStr | None = None
    parent_id: _IdStr = Field(default=None, alias="parentId")


class CustomFieldGroupAttributes(BaseModel):
    """Wire shape for `custom-field-groups` attributes (subset we need)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: _StrippedStr | None = None
    full_path_name: Annotated[list[object] | None, BeforeValidator(_list_or_none)] = Field(
        default=None, alias="fullPathName"
    )
    parent: Annotated[
        CustomFieldGroupParentAttributes | None, BeforeValidator(_mapping_or_none)
    ] = None
