"""One location write: omit `location_id` to create, pass it to patch."""

from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator

from backstop_mcp.features.party_resolver import blank_to_none
from backstop_mcp.models import NonEmptyStr

__all__ = [
    "ContactLocationInput",
    "DELETE_LOCATION_IDS_DESCRIPTION",
    "LOCATIONS_DESCRIPTION",
    "reject_location_write_conflicts",
]

_INCLUDE_HINT = (
    "The location id comes from `get_person` / `get_organization` with "
    "`include=contactLocations` — not `include=locations`, which is a hard 400."
)
_CHANGE_FIELDS = frozenset(
    {
        "location_title",
        "address",
        "city",
        "state",
        "country",
        "postal_code",
        "phone_number",
        "secondary_phone_number",
        "fax",
        "note",
        "is_primary_location",
    }
)


class ContactLocationInput(BaseModel):
    """Create or patch one postal address. No `location_id` means create."""

    location_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Backstop `contact-locations` id to patch. Omit to create a new address. "
            + _INCLUDE_HINT
        ),
    )
    location_title: NonEmptyStr | None = Field(
        default=None,
        max_length=30,
        description=(
            "Label for this address, unique per party (e.g. Office, Home). Required "
            "when creating. At most 30 characters. A duplicate title is a collision, "
            "not a second address."
        ),
    )
    address: NonEmptyStr | None = Field(default=None, description="Street address.")
    city: NonEmptyStr | None = Field(default=None, description="City.")
    state: NonEmptyStr | None = Field(default=None, description="State or province.")
    country: NonEmptyStr | None = Field(default=None, description="Country.")
    postal_code: NonEmptyStr | None = Field(default=None, description="Postal or ZIP code.")
    phone_number: NonEmptyStr | None = Field(
        default=None, description="Phone for this address, not the contact in general."
    )
    secondary_phone_number: NonEmptyStr | None = Field(
        default=None, description="Secondary phone for this address."
    )
    fax: NonEmptyStr | None = Field(default=None, description="Fax for this address.")
    note: NonEmptyStr | None = Field(default=None, description="Note on this address.")
    is_primary_location: bool | None = Field(
        default=None, description="Whether this is the party's primary address."
    )

    @field_validator("location_id", mode="before")
    @classmethod
    def _blank_id_to_none(cls, value: object) -> object:
        return blank_to_none(value)

    @model_validator(mode="after")
    def _create_needs_title_update_needs_a_change(self) -> Self:
        has_change = any(getattr(self, name) is not None for name in _CHANGE_FIELDS)
        if self.location_id is None:
            if self.location_title is None:
                raise ValueError("location_title is required when creating a location")
            return self
        if not has_change:
            raise ValueError("Pass at least one location field to change")
        return self


LOCATIONS_DESCRIPTION = (
    "Postal addresses to create or patch. The party keeps a list — pass one object per "
    + "address. Omit `location_id` to create (`location_title` required, unique on the "
    + "party). Pass `location_id` to patch. "
    + _INCLUDE_HINT
    + " Cannot patch and delete the same id."
)
DELETE_LOCATION_IDS_DESCRIPTION = (
    "Hard-delete these `contact-locations` ids. Deletes run before creates so a title "
    + "can be reused on the same call. "
    + _INCLUDE_HINT
)


def reject_location_write_conflicts(
    *,
    locations: tuple[ContactLocationInput, ...] | None,
    delete_location_ids: tuple[str, ...] | None,
) -> None:
    """Reject overlapping or duplicate location ids in one write."""
    patched = tuple(loc.location_id for loc in (locations or ()) if loc.location_id is not None)
    if len(patched) != len(set(patched)):
        raise ValueError("locations location_id values must be unique")
    deleted = delete_location_ids or ()
    if len(deleted) != len(set(deleted)):
        raise ValueError("delete_location_ids must be unique")
    if set(patched) & set(deleted):
        raise ValueError("Cannot patch and delete the same location_id")
    created_titles = tuple(
        loc.location_title.casefold()
        for loc in (locations or ())
        if loc.location_id is None and loc.location_title is not None
    )
    if len(created_titles) != len(set(created_titles)):
        raise ValueError("location_title must be unique on the party")
