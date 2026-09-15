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

    first_name: NonEmptyStr | None = Field(default=None, description="Replacement first name.")
    middle_name: NonEmptyStr | None = Field(default=None, description="Replacement middle name.")
    nick_name: NonEmptyStr | None = Field(default=None, description="Replacement nickname.")
    prefix: NonEmptyStr | None = Field(default=None, description="Replacement name prefix.")
    suffix: NonEmptyStr | None = Field(default=None, description="Replacement name suffix.")
    salutation: NonEmptyStr | None = Field(default=None, description="Replacement salutation.")
    pronunciation: NonEmptyStr | None = Field(
        default=None, description="Replacement pronunciation guide."
    )
    birthday: date | None = Field(default=None, description="Replacement birthday.")
    spouse_name: NonEmptyStr | None = Field(default=None, description="Replacement spouse name.")
    job_title: NonEmptyStr | None = Field(
        default=None,
        max_length=140,
        description=(
            "Replacement job title. At most 140 characters — Backstop silently stores "
            "over-length values on this endpoint."
        ),
    )
    department: NonEmptyStr | None = Field(default=None, description="Replacement department.")
    company_name: NonEmptyStr | None = Field(
        default=None, description="Replacement company-name text on the person."
    )
    contact_description: NonEmptyStr | None = Field(
        default=None, description="Replacement contact description."
    )
    email: NonEmptyStr | None = Field(
        default=None,
        max_length=255,
        description="Replacement primary email. At most 255 characters.",
    )
    email2: NonEmptyStr | None = Field(
        default=None,
        max_length=255,
        description="Replacement second email. At most 255 characters.",
    )
    email3: NonEmptyStr | None = Field(
        default=None, max_length=255, description="Replacement third email. At most 255 characters."
    )
    mobile_phone: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Replacement mobile phone. Backstop normalizes the stored value; the response "
            "reports the re-read number, not this one."
        ),
    )
    website: NonEmptyStr | None = Field(default=None, description="Replacement website.")
    other_id: NonEmptyStr | None = Field(default=None, description="Replacement external/other id.")
    investable_assets: float | None = Field(
        default=None, description="Replacement investable assets."
    )
    is_employee: bool | None = Field(
        default=None, description="Whether this person is an employee."
    )
    company_id: NonEmptyStr | None = Field(
        default=None,
        description="Replacement employer organization id. Never invent or guess.",
    )
    contact_source_id: NonEmptyStr | None = Field(
        default=None,
        description="Replacement contact-source id. Never invent or guess.",
    )
    referral_source_id: NonEmptyStr | None = Field(
        default=None,
        description="Replacement referral-source contact id (`contacts`). Never invent or guess.",
    )
    owner_login: NonEmptyStr | None = Field(
        default=None,
        description=(
            "Replacement owner of this relationship: the colleague at our own firm. A "
            "`list_system_users` login (`userName`), not a system-user id. Backstop's "
            "`representative`."
        ),
    )
