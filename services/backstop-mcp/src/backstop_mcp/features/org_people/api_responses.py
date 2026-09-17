"""Wire shapes for the person, organization, and employee-card GETs.

Every field is optional and every scalar lenient: a person or organization GET carries whatever
fields the instance configured, and `/employees` is walked a page at a time, so a required field
or a strict type would fail a whole record — or a whole page — over one unparseable value.
`extra="ignore"` keeps these models to the fields this feature reads.

The published `PersonRecordResponse` / `OrganizationRecordResponse` still pass unrecognized
Backstop fields through (`extra="allow"`), and `extra="ignore"` here would drop them before that
happens. `_PartyAttributes` therefore keeps the resource's own `attributes` object as it arrived,
and `passthrough()` hands back the keys that are not one of the modelled wire aliases.
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
from backstop_mcp.dates import LenientDate
from backstop_mcp.features.custom_fields import RegularCustomFieldValues
from backstop_mcp.lenient import LenientBool, LenientFloat, LenientInt, LenientStr

__all__ = [
    "EmployeeAttributes",
    "EmployeeResource",
    "OrganizationAttributes",
    "PersonAttributes",
]


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


def _string_tuple(value: object) -> object:
    """Accept a list of strings; empty becomes None."""
    if value is None:
        return None
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    names = tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    return names or None


class _PartyAttributes(BaseModel):
    """Scalars both party records share, plus the raw object they arrived in."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    # `validation_alias`, not `alias`: the camelCase spelling is what Backstop sends, and a
    # `model_dump` of anything built from this stays snake_case.
    name: LenientStr = None
    contact_description: LenientStr = Field(default=None, validation_alias="contactDescription")
    created_timestamp: LenientStr = Field(default=None, validation_alias="createdTimestamp")
    email: LenientStr = None
    email2: LenientStr = None
    email3: LenientStr = None
    website: LenientStr = None
    other_id: LenientStr = Field(default=None, validation_alias="otherId")
    investable_assets: LenientFloat = Field(default=None, validation_alias="investableAssets")
    landing_page_url: LenientStr = Field(default=None, validation_alias="landingPageUrl")
    legal_name: LenientStr = Field(default=None, validation_alias="legalName")
    sync_disabled: LenientBool = Field(default=None, validation_alias="syncDisabled")
    categories_as_string: LenientStr = Field(default=None, validation_alias="categoriesAsString")
    categories: Annotated[tuple[str, ...] | None, BeforeValidator(_extract_category_names)] = None
    country: LenientStr = None
    city: LenientStr = None
    postal_code: LenientStr = Field(default=None, validation_alias="postalCode")
    state: LenientStr = None
    fax: LenientStr = None
    location_title: LenientStr = Field(default=None, validation_alias="locationTitle")
    primary_phone_number: LenientStr = Field(default=None, validation_alias="primaryPhoneNumber")
    phone: LenientStr = None
    street_address: LenientStr = Field(default=None, validation_alias="streetAddress")
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
        return {key: value for key, value in self._wire.items() if key not in self._known_wire_keys}

    @property
    def _known_wire_keys(self) -> frozenset[str]:
        keys: set[str] = set()
        for name, field in type(self).model_fields.items():
            keys.add(name)
            alias = field.validation_alias
            if isinstance(alias, str):
                keys.add(alias)
        return frozenset(keys)


class PersonAttributes(_PartyAttributes):
    """A `people` / `contacts` / `employees` resource's `attributes`, as Backstop sends them."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    birthday: LenientDate = None
    company_name: LenientStr = Field(default=None, validation_alias="companyName")
    department: LenientStr = None
    first_name: LenientStr = Field(default=None, validation_alias="firstName")
    middle_name: LenientStr = Field(default=None, validation_alias="middleName")
    last_name: LenientStr = Field(default=None, validation_alias="lastName")
    gender: LenientStr = None
    is_employee: LenientBool = Field(default=None, validation_alias="isEmployee")
    is_key_employee: LenientBool = Field(default=None, validation_alias="isKeyEmployee")
    job_title: LenientStr = Field(default=None, validation_alias="jobTitle")
    mobile_phone: LenientStr = Field(default=None, validation_alias="mobilePhone")
    nick_name: LenientStr = Field(default=None, validation_alias="nickName")
    prefix: LenientStr = None
    suffix: LenientStr = None
    salutation: LenientStr = None
    pronunciation: LenientStr = None
    spouse_name: LenientStr = Field(default=None, validation_alias="spouseName")


class OrganizationAttributes(_PartyAttributes):
    """An `organizations` resource's `attributes`, as Backstop sends them."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    aliases: LenientStr = None
    date_founded: LenientDate = Field(default=None, validation_alias="dateFounded")
    internal_organization: LenientBool = Field(
        default=None, validation_alias="internalOrganization"
    )
    matching_domains: Annotated[tuple[str, ...] | None, BeforeValidator(_string_tuple)] = Field(
        default=None, validation_alias="matchingDomains"
    )
    number_of_employees: LenientInt = Field(default=None, validation_alias="numberOfEmployees")
    ria: LenientBool = None


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
    is_key_employee: LenientBool = Field(default=None, validation_alias="isKeyEmployee")


EmployeeResource = BackstopApiResource[EmployeeAttributes]
