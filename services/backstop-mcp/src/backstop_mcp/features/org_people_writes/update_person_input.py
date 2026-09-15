"""PATCH fields for `update_person`.

Identity uses the same resolver as `get_person`: `search`, `party_id`, `search_type`.
Every other field is optional — omit to leave it unchanged. At least one change field
must be set.

Excluded: `name` and `legalName` are derived from the name parts — write `first_name` /
`last_name`. `categoriesAsString` is a denormalized mirror of `categories`. `groupEntities`
is a nested relationship feature, not a field here. `regularCustomFieldValues` goes
through `update_custom_field_values`. `permissionBucket`, `contactTemplate`,
`syncDisabled`, and `hasRecommendationViewed` are out of scope. Do not touch
`contact-emails`; email corrections go through `email` / `email2` / `email3`.
"""

from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from backstop_mcp.features.org_people_writes._person_writable_fields import (
    GENDER_DESCRIPTION,
    LAST_NAME_DESCRIPTION,
    _PersonWritableFields,
)
from backstop_mcp.features.org_people_writes.contact_location_input import ContactLocationInput
from backstop_mcp.features.party_resolver import (
    PARTY_ID_REQUIRES_SEARCH_TYPE_DESCRIPTION,
    SEARCH_REQUIRES_SEARCH_TYPE_DESCRIPTION,
    blank_to_none,
    require_exactly_one_party_selector,
)
from backstop_mcp.models import NonEmptyStr

__all__ = [
    "UPDATE_PERSON_INPUT_DESCRIPTION",
    "UpdatePersonInput",
]

UPDATE_PERSON_INPUT_DESCRIPTION = (
    "Required. The person to patch. Needs exactly one of `party_id` or `search`, plus "
    "`search_type` (defaults to people), and at least one field to change. `last_name` "
    "cannot be cleared. Custom fields go through `update_custom_field_values`. Location "
    "ids come from `get_person` with `include=contactLocations`, not `include=locations`. "
    "Omit a field to leave it unchanged. Never invent an id."
)

_IDENTITY_FIELDS = frozenset({"party_id", "search", "search_type"})
_PERSON_SEARCH_TYPE_DESCRIPTION = (
    "Collection to resolve against. Echo `search_type` from a prior resolve when retrying "
    "with `party_id` — a contact or employee id is not a people id. Defaults to people."
)
_LOCATION_ID_HINT = (
    "Ids come from `get_person` with `include=contactLocations`, not `include=locations`."
)


class _UpdatePersonIdentity(BaseModel):
    """Party selectors. Inherited first so they lead the published schema."""

    search_type: Literal["people", "contacts", "employees"] = Field(
        default="people", description=_PERSON_SEARCH_TYPE_DESCRIPTION
    )
    party_id: NonEmptyStr | None = Field(
        default=None, description=PARTY_ID_REQUIRES_SEARCH_TYPE_DESCRIPTION
    )
    search: NonEmptyStr | None = Field(
        default=None, description=SEARCH_REQUIRES_SEARCH_TYPE_DESCRIPTION
    )

    @field_validator("party_id", "search", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        return blank_to_none(value)

    @model_validator(mode="after")
    def _exactly_one_selector(self) -> Self:
        require_exactly_one_party_selector(party_id=self.party_id, search=self.search)
        return self


class UpdatePersonInput(_UpdatePersonIdentity, _PersonWritableFields):
    """PATCH a person. Only supplied fields are sent; PATCH is merge."""

    last_name: str | None = Field(default=None, description=LAST_NAME_DESCRIPTION)
    gender: NonEmptyStr | None = Field(default=None, description=GENDER_DESCRIPTION)
    add_category_ids: tuple[str, ...] | None = Field(
        default=None,
        min_length=1,
        description=(
            "Contact-category ids to append. One PATCH; Backstop appends to-many "
            "relationships. Cannot be combined with `replace_category_ids`. To clear, "
            "use `replace_category_ids=[]`."
        ),
    )
    replace_category_ids: tuple[str, ...] | None = Field(
        default=None,
        description=(
            "Set the categories to exactly these ids. Two PATCHes (clear, then add) "
            "because a to-many PATCH appends and `data: []` is the only clear. An empty "
            "tuple clears. Cannot be combined with `add_category_ids`. There is no way "
            "to remove a single member."
        ),
    )
    location: ContactLocationInput | None = Field(
        default=None,
        description=(
            "Create or patch one postal address. Omit `location_id` to create "
            + "(`location_title` required, unique on the party). Pass `location_id` to "
            + "patch. "
            + _LOCATION_ID_HINT
        ),
    )
    delete_location_id: NonEmptyStr | None = Field(
        default=None,
        description="Hard-delete this `contact-locations` id. " + _LOCATION_ID_HINT,
    )

    # `mode="before"` runs only when the key is present, so an explicit null is told
    # apart from an omitted field.
    @field_validator("last_name", mode="before")
    @classmethod
    def _last_name_cannot_be_cleared(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError("last_name cannot be cleared; Field lastName is required")
        return value

    @model_validator(mode="after")
    def _at_least_one_change(self) -> Self:
        for name in type(self).model_fields:
            if name in _IDENTITY_FIELDS:
                continue
            if getattr(self, name) is not None:
                return self
        raise ValueError("Pass at least one field to change")

    @model_validator(mode="after")
    def _category_fields_are_exclusive(self) -> Self:
        if self.add_category_ids is not None and self.replace_category_ids is not None:
            raise ValueError("Set add_category_ids or replace_category_ids, not both")
        return self
