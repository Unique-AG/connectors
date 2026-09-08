"""Wire shapes for the person, organization, and employee-card GETs.

Every field is optional and every scalar lenient: a person or organization GET carries whatever
fields the instance configured, and `/employees` is walked a page at a time, so a required field
or a strict type would fail a whole record — or a whole page — over one unparseable value.
`extra="ignore"` keeps these models to the fields this feature reads.

The published `PersonRecordResponse` / `OrganizationRecordResponse` still pass unrecognized
Backstop fields through (`extra="allow"`), and `extra="ignore"` here would drop them before that
happens. `_PartyAttributes` therefore keeps the resource's own `attributes` object as it arrived,
and `passthrough()` hands back the keys that are not one of the known wire aliases.
"""

from collections.abc import Mapping, Sequence
from typing import Annotated, ClassVar, Self, cast

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    PrivateAttr,
    model_validator,
)

from backstop_mcp.backstop_client import BackstopApiResource
from backstop_mcp.features.custom_fields import RegularCustomFieldValues
from backstop_mcp.lenient import LenientStr

__all__ = [
    "EmployeeAttributes",
    "EmployeeResource",
    "OrganizationAttributes",
    "PersonAttributes",
]

_KNOWN_WIRE_KEYS = frozenset(
    {"name", "regularCustomFieldValues", "modifiedTimestamp", "modifiedBy"}
)


def _mapping_name(item: Mapping[object, object]) -> str | None:
    raw_name = item.get("name")
    if isinstance(raw_name, str) and raw_name.strip():
        return raw_name.strip()
    return None


def _extract_category_names(value: object) -> object:
    """Accept a list of strings or `{name}` objects; empty becomes None."""
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    names: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
        elif isinstance(item, Mapping):
            raw_name = _mapping_name(cast("Mapping[object, object]", item))
            if raw_name is not None:
                names.append(raw_name)
    return tuple(names) or None


class _PartyAttributes(BaseModel):
    """The attributes both party records share, plus the raw object they arrived in."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    # `validation_alias`, not `alias`: the camelCase spelling is what Backstop sends, and a
    # `model_dump` of anything built from this stays snake_case.
    name: LenientStr = None
    regular_custom_field_values: RegularCustomFieldValues = Field(
        default_factory=list, validation_alias="regularCustomFieldValues"
    )
    modified_timestamp: LenientStr = Field(default=None, validation_alias="modifiedTimestamp")
    # Not lenient: `modifiedBy` arrives as a string on some instances and as an actor object on
    # others, and `AsOfResponse.from_attributes` is what reads a name out of either.
    modified_by: object | None = Field(default=None, validation_alias="modifiedBy")

    _wire: dict[str, object] = PrivateAttr(default_factory=dict)

    @model_validator(mode="wrap")
    @classmethod
    def _capture_wire(cls, data: object, handler: ModelWrapValidatorHandler[Self]) -> Self:
        model = handler(data)
        if isinstance(data, Mapping):
            model._wire = {
                str(key): value for key, value in cast("Mapping[object, object]", data).items()
            }
        return model

    def passthrough(self) -> dict[str, object]:
        """Wire keys this feature does not model, for the published record to carry through."""
        return {key: value for key, value in self._wire.items() if key not in _KNOWN_WIRE_KEYS}


class PersonAttributes(_PartyAttributes):
    """A `people` / `contacts` / `employees` resource's `attributes`, as Backstop sends them."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)


class OrganizationAttributes(_PartyAttributes):
    """An `organizations` resource's `attributes`, as Backstop sends them."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)


class EmployeeAttributes(BaseModel):
    """The sparse `employees` fieldset walked for an organization's roster.

    Exactly the fields `fields[employees]` asks for. Deliberately not the published
    `ContactCardResponse`: that model is the tool payload, and using it as a page schema would
    make a display contract responsible for surviving the wire.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    name: LenientStr = None
    job_title: LenientStr = Field(default=None, validation_alias="jobTitle")
    email: LenientStr = None
    phone: LenientStr = None
    company_name: LenientStr = Field(default=None, validation_alias="companyName")
    categories: Annotated[tuple[str, ...] | None, BeforeValidator(_extract_category_names)] = None


EmployeeResource = BackstopApiResource[EmployeeAttributes]
