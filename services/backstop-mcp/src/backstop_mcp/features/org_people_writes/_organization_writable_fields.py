"""Optional organization fields shared by create and update."""

from datetime import date

from pydantic import BaseModel, Field

from backstop_mcp.models import NonEmptyStr

__all__ = [
    "NAME_DESCRIPTION",
    "_OrganizationWritableFields",
]

NAME_DESCRIPTION = (
    "Replacement organization name. Required on the record; clearing it is "
    "rejected. At most 50 characters — Backstop silently stores over-length "
    "values on this endpoint."
)


class _OrganizationWritableFields(BaseModel):
    """Fields optional on both `create_organization` and `update_organization`."""

    legal_name: NonEmptyStr | None = Field(default=None, description="Legal name.")
    aliases: NonEmptyStr | None = Field(default=None, description="Aliases string.")
    contact_description: NonEmptyStr | None = Field(
        default=None, description="Contact description."
    )
    date_founded: date | None = Field(default=None, description="Date founded.")
    email: NonEmptyStr | None = Field(
        default=None,
        max_length=255,
        description="Primary email. At most 255 characters.",
    )
    email2: NonEmptyStr | None = Field(
        default=None,
        max_length=255,
        description="Second email. At most 255 characters.",
    )
    email3: NonEmptyStr | None = Field(
        default=None, max_length=255, description="Third email. At most 255 characters."
    )
    website: NonEmptyStr | None = Field(default=None, description="Website.")
    other_id: NonEmptyStr | None = Field(default=None, description="External/other id.")
    investable_assets: float | None = Field(default=None, description="Investable assets.")
    number_of_employees: int | None = Field(
        default=None,
        description=(
            "Headcount on the organization record. This is not a roster — current staff "
            "come from `get_people_for_party`."
        ),
    )
    internal_organization: bool | None = Field(
        default=None, description="Whether this is an internal organization."
    )
    ria: bool | None = Field(default=None, description="Whether this organization is an RIA.")
    matching_domains: tuple[str, ...] | None = Field(
        default=None, description="List of matching email domains."
    )
    contact_source_id: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Contact-source id from `list_contact_sources`. A standard vocabulary, "
            "not a custom field. Never invent or guess."
        ),
    )
    referral_source_id: NonEmptyStr | None = Field(
        default=None,
        description="Referral-source contact id (`contacts`). Never invent or guess.",
    )
    owner_login: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Owner of this relationship: the colleague at our own firm. A "
            "`list_system_users` login (`userName`), not a system-user id. Backstop's "
            "`representative`."
        ),
    )
    primary_contact_id: NonEmptyStr | None = Field(
        default=None,
        description="Primary contact people id. Never invent or guess.",
    )
