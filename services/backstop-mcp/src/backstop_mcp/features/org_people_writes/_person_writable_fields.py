"""Optional person fields shared by create and update."""

from datetime import date

from pydantic import BaseModel, Field

from backstop_mcp.models import NonEmptyStr

__all__ = [
    "GENDER_DESCRIPTION",
    "LAST_NAME_DESCRIPTION",
    "_PersonWritableFields",
]

LAST_NAME_DESCRIPTION = (
    "Replacement last name. Required on the record; clearing it is rejected "
    "(`Field lastName is required`)."
)
GENDER_DESCRIPTION = "Replacement gender."


class _PersonWritableFields(BaseModel):
    """Fields optional on both `create_person` and `update_person`."""

    first_name: NonEmptyStr | None = Field(default=None, description="First name.")
    middle_name: NonEmptyStr | None = Field(default=None, description="Middle name.")
    nick_name: NonEmptyStr | None = Field(default=None, description="Nickname.")
    prefix: NonEmptyStr | None = Field(default=None, description="Name prefix.")
    suffix: NonEmptyStr | None = Field(default=None, description="Name suffix.")
    salutation: NonEmptyStr | None = Field(default=None, description="Salutation.")
    pronunciation: NonEmptyStr | None = Field(default=None, description="Pronunciation guide.")
    birthday: date | None = Field(default=None, description="Birthday.")
    spouse_name: NonEmptyStr | None = Field(default=None, description="Spouse name.")
    job_title: NonEmptyStr | None = Field(
        default=None,
        max_length=140,
        description=(
            "Job title. At most 140 characters — Backstop silently stores over-length "
            "values on this endpoint."
        ),
    )
    department: NonEmptyStr | None = Field(default=None, description="Department.")
    company_name: NonEmptyStr | None = Field(
        default=None, description="Company-name text on the person."
    )
    contact_description: NonEmptyStr | None = Field(
        default=None, description="Contact description."
    )
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
    mobile_phone: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Mobile phone. Backstop normalizes the stored value; the response reports "
            "the re-read number, not this one."
        ),
    )
    website: NonEmptyStr | None = Field(default=None, description="Website.")
    other_id: NonEmptyStr | None = Field(default=None, description="External/other id.")
    investable_assets: float | None = Field(default=None, description="Investable assets.")
    is_employee: bool | None = Field(
        default=None, description="Whether this person is an employee."
    )
    company_id: NonEmptyStr | None = Field(
        default=None,
        description="Employer organization id. Never invent or guess.",
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
