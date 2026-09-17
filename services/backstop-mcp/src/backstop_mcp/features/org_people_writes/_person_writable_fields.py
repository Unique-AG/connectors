"""Optional person fields shared by create and update."""

from datetime import date

from pydantic import BaseModel, Field, field_validator

from backstop_mcp.models import NonEmptyStr

__all__ = [
    "GENDER_DESCRIPTION",
    "KEY_EMPLOYEE_NOT_WRITABLE",
    "KEY_EMPLOYEE_NOT_WRITABLE_DESCRIPTION",
    "LAST_NAME_DESCRIPTION",
    "_PersonWritableFields",
    "reject_key_employee_write",
]

LAST_NAME_DESCRIPTION = (
    "Replacement last name. Required on the record; clearing it is rejected "
    "(`Field lastName is required`)."
)
GENDER_DESCRIPTION = "Replacement gender."
KEY_EMPLOYEE_NOT_WRITABLE = (
    "is_key_employee cannot be written through the API. Personal API tokens do not "
    "persist isKeyRelationship; set Key employee in the Backstop CRM UI. Read it on "
    "get_people_for_party."
)
KEY_EMPLOYEE_NOT_WRITABLE_DESCRIPTION = (
    "Not writable. Personal API tokens do not persist Key employee "
    "(`isKeyRelationship` on the employment row / `isKeyEmployee` on the org roster). "
    "Set it in the Backstop CRM UI. Read it on `get_people_for_party`. Distinct from "
    "`is_employee`."
)


def reject_key_employee_write(value: bool | None) -> bool | None:
    if value is not None:
        raise ValueError(KEY_EMPLOYEE_NOT_WRITABLE)
    return value


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
        default=None,
        description=(
            "Whether this person is an employee of our firm (`isEmployee`). "
            "Distinct from `is_key_employee`."
        ),
    )
    is_key_employee: bool | None = Field(
        default=None,
        description=KEY_EMPLOYEE_NOT_WRITABLE_DESCRIPTION,
    )

    @field_validator("is_key_employee")
    @classmethod
    def _key_employee_is_not_writable(cls, value: bool | None) -> bool | None:
        return reject_key_employee_write(value)

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
