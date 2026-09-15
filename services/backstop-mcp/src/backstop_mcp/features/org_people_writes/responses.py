"""Published party-write responses.

A write reports the id, the resource type, and only the extra fields a measured trap
requires: the phone Backstop stored (it rewrites numbers), and a location id when one
was created or updated.
"""

from datetime import date
from typing import Literal

from pydantic import Field

from backstop_mcp.features.party_resolver import PartyAmbiguousResponse
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.models import OmitNoneModel

__all__ = [
    "CreatedOrganizationResponse",
    "CreatedPersonResponse",
    "EndEmploymentResponse",
    "EndedEmploymentResponse",
    "UpdateOrganizationResponse",
    "UpdatePersonResponse",
    "UpdatedOrganizationResponse",
    "UpdatedPersonResponse",
]


class CreatedPersonResponse(OmitNoneModel):
    """A person after a POST, with the name and phone Backstop actually stored."""

    id: str = Field(description="Backstop id of the created person. Echo it; never invent one.")
    resource_type: Literal["people"] = Field(
        default="people",
        description="Always `people`.",
    )
    name: str | None = Field(
        default=None,
        description="Display name READ BACK after the write.",
    )
    mobile_phone: str | None = Field(
        default=None,
        description=(
            "Mobile phone READ BACK after the write. Backstop normalizes numbers "
            "(e.g. `+1 555 0100` is stored as `555-0100`); this is the stored value, "
            "not the requested one."
        ),
    )
    warnings: tuple[str, ...] = Field(
        default=(),
        description="Silent-failure notes. Empty when the write landed as asked.",
    )


class CreatedOrganizationResponse(OmitNoneModel):
    """An organization after a POST, with the name Backstop actually stored."""

    id: str = Field(
        description="Backstop id of the created organization. Echo it; never invent one."
    )
    resource_type: Literal["organizations"] = Field(
        default="organizations",
        description="Always `organizations`.",
    )
    name: str | None = Field(
        default=None,
        description="Organization name READ BACK after the write.",
    )
    warnings: tuple[str, ...] = Field(
        default=(),
        description="Silent-failure notes. Empty when the write landed as asked.",
    )


class UpdatedPersonResponse(OmitNoneModel):
    """A person after a PATCH, with the phone Backstop actually stored."""

    id: str = Field(description="Backstop id of the person. Echo it; never invent one.")
    resource_type: Literal["people"] = Field(
        default="people",
        description="Always `people`.",
    )
    mobile_phone: str | None = Field(
        default=None,
        description=(
            "Mobile phone READ BACK after the write. Backstop normalizes numbers "
            "(e.g. `+1 555 0100` is stored as `555-0100`); this is the stored value, "
            "not the requested one."
        ),
    )
    location_id: str | None = Field(
        default=None,
        description=(
            "Backstop `contact-locations` id created or updated on this call. Echo it "
            "as `location.location_id`. From `get_person` with "
            "`include=contactLocations` — not `include=locations`."
        ),
    )
    warnings: tuple[str, ...] = Field(
        default=(),
        description="Silent-failure notes. Empty when the write landed as asked.",
    )


class UpdatedOrganizationResponse(OmitNoneModel):
    """An organization after a PATCH."""

    id: str = Field(description="Backstop id of the organization. Echo it; never invent one.")
    resource_type: Literal["organizations"] = Field(
        default="organizations",
        description="Always `organizations`.",
    )
    location_id: str | None = Field(
        default=None,
        description=(
            "Backstop `contact-locations` id created or updated on this call. Echo it "
            "as `location.location_id`. From `get_organization` with "
            "`include=contactLocations` — not `include=locations`."
        ),
    )
    warnings: tuple[str, ...] = Field(
        default=(),
        description="Silent-failure notes. Empty when the write landed as asked.",
    )


type UpdatePersonResponse = UpdatedPersonResponse | PartyAmbiguousResponse | NotFoundResponse


class EndedEmploymentResponse(OmitNoneModel):
    """An employment relationship after `endDate` was written."""

    id: str = Field(
        description="Backstop `entity-relationships` id that received `endDate`. Echo it."
    )
    resource_type: Literal["entity-relationships"] = Field(
        default="entity-relationships",
        description="Always `entity-relationships`.",
    )
    end_date: date | None = Field(
        default=None,
        description="`endDate` READ BACK after the write, as YYYY-MM-DD.",
    )
    warnings: tuple[str, ...] = Field(
        default=(),
        description=(
            "Silent-failure notes. A date that is not strictly before today is recorded "
            "but the person still reads as a current contact until it passes."
        ),
    )


type UpdateOrganizationResponse = (
    UpdatedOrganizationResponse | PartyAmbiguousResponse | NotFoundResponse
)

type EndEmploymentResponse = EndedEmploymentResponse | PartyAmbiguousResponse | NotFoundResponse
