from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

_StrippedStr = Annotated[str, StringConstraints(strip_whitespace=True)]

# The relationship name `custom-field-definitions` exposes for its list-of-values set. Per the
# swagger this is the *only* accepted `?include=` target for the endpoint.
LOV_SET_RELATIONSHIP = "lovSet"


class CustomFieldDefinitionAttributes(BaseModel):
    """Wire shape for `custom-field-definitions` attributes (subset we need)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: _StrippedStr | None = None
    entity_type: _StrippedStr | None = Field(default=None, alias="entityType")
    field_type: _StrippedStr | None = Field(default=None, alias="fieldType")
    field_type_display: _StrippedStr | None = Field(default=None, alias="fieldTypeDisplay")
    is_time_series: bool | None = Field(default=None, alias="isTimeSeries")
    # Backstop also exposes `lovSet` as a *relationship* (see `LOV_SET_RELATIONSHIP`); these
    # two attributes cover instances that inline the options instead. Both paths feed
    # `lov.allowed_values_for`.
    lov_set: object | None = Field(default=None, alias="lovSet")
    select_options: object | None = Field(default=None, alias="selectOptions")
    description: _StrippedStr | None = None
    required: bool | None = None
    client_required: bool | None = Field(default=None, alias="clientRequired")
    system_defined: bool | None = Field(default=None, alias="systemDefined")


class LovEntryAttributes(BaseModel):
    """Wire shape for `lov-entries` attributes.

    Field names are from the swagger's create example for `/lov-entries`: required fields are
    `display`, `viewable`, `setId`, `position`.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    display: _StrippedStr | None = None
    default_display: _StrippedStr | None = Field(default=None, alias="defaultDisplay")
    code: _StrippedStr | None = None
    set_id: object | None = Field(default=None, alias="setId")
    position: int | None = None
    viewable: bool | None = None


class AllowedValue(BaseModel):
    """One picklist / LOV entry, usable to validate a write before attempting it."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str | None = None
    label: str


class CustomFieldDefinition(BaseModel):
    """Merged CRM definition + optional human override."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    definition_id: str
    entity_type: str
    crm_name: str
    display_name: str
    aliases: tuple[str, ...] = ()
    description: str | None = None
    field_type: str | None = None
    field_type_display: str | None = None
    is_time_series: bool = False
    allowed_values: tuple[AllowedValue, ...] = ()
    # The `lovSet` id this definition points at, when it uses the relationship form. Kept so a
    # snapshot can be re-joined against LOV entries without re-reading the raw payload.
    lov_set_id: str | None = None
    raw: dict[str, object] = Field(default_factory=dict)
