from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

_StrippedStr = Annotated[str, StringConstraints(strip_whitespace=True)]

# API path segments / glossary scopes we care about for IR workflows.
type EntityType = Literal[
    "organizations",
    "contacts",
    "people",
    "employees",
    "opportunities",
    "accounts",
]


class CustomFieldDefinitionAttributes(BaseModel):
    """Wire shape for `custom-field-definitions` attributes (subset we need)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    name: _StrippedStr | None = None
    entity_type: _StrippedStr | None = Field(default=None, alias="entityType")
    field_type: _StrippedStr | None = Field(default=None, alias="fieldType")
    field_type_display: _StrippedStr | None = Field(default=None, alias="fieldTypeDisplay")
    is_time_series: bool | None = Field(default=None, alias="isTimeSeries")
    lov_set: object | None = Field(default=None, alias="lovSet")
    select_options: object | None = Field(default=None, alias="selectOptions")
    description: _StrippedStr | None = None
    required: bool | None = None
    client_required: bool | None = Field(default=None, alias="clientRequired")
    system_defined: bool | None = Field(default=None, alias="systemDefined")


@dataclass(frozen=True)
class AllowedValue:
    """One picklist / LOV entry usable for write validation later."""

    id: str | None
    label: str


@dataclass(frozen=True)
class CustomFieldDefinition:
    """Merged CRM definition + optional human override."""

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
    raw: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FieldCandidate:
    definition_id: str
    display_name: str
    crm_name: str
    entity_type: str
    label: str


@dataclass(frozen=True)
class FieldResolved:
    definition: CustomFieldDefinition
    status: Literal["resolved"] = "resolved"


@dataclass(frozen=True)
class FieldAmbiguous:
    query: str
    entity_type: str
    candidates: tuple[FieldCandidate, ...]
    status: Literal["ambiguous"] = "ambiguous"


@dataclass(frozen=True)
class FieldNotFound:
    query: str
    entity_type: str
    status: Literal["not_found"] = "not_found"


type FieldResolveResult = FieldResolved | FieldAmbiguous | FieldNotFound
