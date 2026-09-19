"""Published party-write responses.

A write reports the id, the resource type, and the extra fields a measured trap
requires: the phone Backstop stored (it rewrites numbers), and location ids when
addresses were created or updated. Person and organization PATCHes also echo the
re-read record — same top-level scalars as `get_person` / `get_organization`.
"""

from datetime import date
from typing import ClassVar, Literal

from pydantic import ConfigDict, Field

from backstop_mcp.features.org_people import OrganizationRecordResponse, PersonRecordResponse
from backstop_mcp.features.party_resolver import PartyAmbiguousResponse
from backstop_mcp.features.resolution import NotFoundResponse
from backstop_mcp.models import OmitNoneModel

_PERSON_URL_DESCRIPTION = (
    "Canonical CRM UI URL for this person (no tab). Omitted when this deployment "
    "has no UI origin. Echo it; never invent one. Call build_backstop_links for "
    "tabs or a layout."
)
_ORGANIZATION_URL_DESCRIPTION = (
    "Canonical CRM UI URL for this organization (no tab). Omitted when this "
    "deployment has no UI origin. Echo it; never invent one. Call "
    "build_backstop_links for tabs or a layout."
)

__all__ = [
    "CreateEmploymentResponse",
    "CreatedEmploymentResponse",
    "CreatedOrganizationResponse",
    "CreatedPersonResponse",
    "DeleteOrganizationResponse",
    "DeletePersonResponse",
    "DeletedOrganizationResponse",
    "DeletedPersonResponse",
    "EndEmploymentResponse",
    "EndedEmploymentResponse",
    "EntityRelationshipTypeResponse",
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
    url: str | None = Field(default=None, description=_PERSON_URL_DESCRIPTION)


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
    url: str | None = Field(default=None, description=_ORGANIZATION_URL_DESCRIPTION)


class DeletedPersonResponse(OmitNoneModel):
    """A hard delete: Backstop has no recycle bin, so `permanent` is always true."""

    id: str = Field(description="Backstop id of the deleted person. Echo it; never invent one.")
    resource_type: Literal["people", "contacts", "employees"] = Field(
        default="people",
        description="Collection the delete targeted: `people`, `contacts`, or `employees`.",
    )
    permanent: Literal[True] = Field(
        default=True,
        description="Always true: Backstop hard-deletes the record. There is no recycle bin.",
    )
    deleted_location_ids: tuple[str, ...] = Field(
        default=(),
        description=(
            "Contact-location ids removed before the person. Empty when the person had "
            "none. From `include=contactLocations` — not `include=locations`."
        ),
    )


class DeletedOrganizationResponse(OmitNoneModel):
    """A hard delete: Backstop has no recycle bin, so `permanent` is always true."""

    id: str = Field(
        description="Backstop id of the deleted organization. Echo it; never invent one."
    )
    resource_type: Literal["organizations"] = Field(
        default="organizations",
        description="Always `organizations`.",
    )
    permanent: Literal[True] = Field(
        default=True,
        description="Always true: Backstop hard-deletes the record. There is no recycle bin.",
    )
    deleted_location_ids: tuple[str, ...] = Field(
        default=(),
        description=(
            "Contact-location ids removed before the organization. Empty when the "
            "organization had none. From `include=contactLocations` — not "
            "`include=locations`."
        ),
    )


class UpdatedPersonResponse(OmitNoneModel):
    """A person after a PATCH, with the record and phone Backstop actually stored."""

    id: str = Field(description="Backstop id of the person. Echo it; never invent one.")
    resource_type: Literal["people", "contacts", "employees"] = Field(
        default="people",
        description="Collection this PATCH targeted: `people`, `contacts`, or `employees`.",
    )
    person: PersonRecordResponse = Field(
        description=(
            "The person record READ BACK after the write. Same top-level fields as "
            "`get_person` (`first_name`, `job_title`, `is_key_employee`, emails, "
            "location copies, …). Custom fields stay on `get_person` / "
            "`update_custom_field_values`."
        ),
    )
    mobile_phone: str | None = Field(
        default=None,
        description=(
            "Mobile phone READ BACK after the write. Backstop normalizes numbers "
            "(e.g. `+1 555 0100` is stored as `555-0100`); this is the stored value, "
            "not the requested one. Also on `person.mobile_phone`."
        ),
    )
    location_ids: tuple[str, ...] = Field(
        default=(),
        description=(
            "Backstop `contact-locations` ids created or updated on this call. Echo them "
            "as `locations[].location_id`. From `get_person` with "
            "`include=contactLocations` — not `include=locations`."
        ),
    )
    warnings: tuple[str, ...] = Field(
        default=(),
        description="Silent-failure notes. Empty when the write landed as asked.",
    )
    url: str | None = Field(default=None, description=_PERSON_URL_DESCRIPTION)


class UpdatedOrganizationResponse(OmitNoneModel):
    """An organization after a PATCH, with the record Backstop actually stored."""

    id: str = Field(description="Backstop id of the organization. Echo it; never invent one.")
    resource_type: Literal["organizations"] = Field(
        default="organizations",
        description="Always `organizations`.",
    )
    organization: OrganizationRecordResponse = Field(
        description=(
            "The organization record READ BACK after the write. Same top-level fields "
            "as `get_organization` (`name`, `legal_name`, `website`, "
            "`number_of_employees`, location copies, …). Custom fields stay on "
            "`get_organization` / `update_custom_field_values`."
        ),
    )
    location_ids: tuple[str, ...] = Field(
        default=(),
        description=(
            "Backstop `contact-locations` ids created or updated on this call. Echo them "
            "as `locations[].location_id`. From `get_organization` with "
            "`include=contactLocations` — not `include=locations`."
        ),
    )
    warnings: tuple[str, ...] = Field(
        default=(),
        description="Silent-failure notes. Empty when the write landed as asked.",
    )
    url: str | None = Field(default=None, description=_ORGANIZATION_URL_DESCRIPTION)


type UpdatePersonResponse = UpdatedPersonResponse | PartyAmbiguousResponse | NotFoundResponse

type DeletePersonResponse = DeletedPersonResponse | PartyAmbiguousResponse | NotFoundResponse


class EntityRelationshipTypeResponse(OmitNoneModel):
    """One row of the instance's entity-relationship-type vocabulary.

    Used to resolve the employment type id a write must send. A row without a name is
    dropped — matching and reporting types is the whole point of this vocabulary.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    id: str = Field(description="Backstop id of this relationship type. Echo it; never invent one.")
    name: str = Field(description="Relationship type name as this instance publishes it.")


class CreatedEmploymentResponse(OmitNoneModel):
    """An employment relationship after a POST.

    One POST also created the reverse mirror row (person→org and org→person).
    """

    id: str = Field(
        description="Backstop `entity-relationships` id of the created employment. Echo it."
    )
    resource_type: Literal["entity-relationships"] = Field(
        default="entity-relationships",
        description="Always `entity-relationships`.",
    )
    start_date: date | None = Field(
        default=None,
        description="`startDate` READ BACK after the write, as YYYY-MM-DD.",
    )
    created_mirror_row: Literal[True] = Field(
        default=True,
        description=(
            "Always true. One POST also created the reverse mirror row (person→org and org→person)."
        ),
    )
    warnings: tuple[str, ...] = Field(
        default=(),
        description="Silent-failure notes. Empty when the write landed as asked.",
    )


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

type DeleteOrganizationResponse = (
    DeletedOrganizationResponse | PartyAmbiguousResponse | NotFoundResponse
)

type EndEmploymentResponse = EndedEmploymentResponse | PartyAmbiguousResponse | NotFoundResponse

type CreateEmploymentResponse = (
    CreatedEmploymentResponse | PartyAmbiguousResponse | NotFoundResponse
)
