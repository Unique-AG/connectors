from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class OmitNoneModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")


class PersonResponse(OmitNoneModel):
    """One contact, as their role at the investor asked about — not their whole career."""

    id: int
    name: str | None = None
    job_title: str | None = Field(default=None, description="Their title at this organisation.")
    seniority: str | None = Field(
        default=None,
        description="The vendor's seniority band. The closest thing to a decision-maker signal.",
    )
    specialism: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin: str | None = None
    biography: str | None = None
    is_main_contact: bool | None = Field(
        default=None, description="Flagged by With Intelligence as the main contact here."
    )
    is_current: bool = Field(
        default=True,
        description=(
            "False when the role has an end date — they have left. Do not write to a former "
            "contact without saying so."
        ),
    )
    role_started: str | None = None
    role_ended: str | None = None


class PeopleForInvestorResponse(OmitNoneModel):
    """Contacts at one investor, with the caveat that the counts do not agree.

    `total_at_organisation` is what the person search reports; `contacts_on_investor_record` is
    what the investor record embeds. They differ — the record's list is longer — and which is
    authoritative is not documented, so both are reported rather than picking one.
    """

    investor_id: int
    investor_name: str | None = None
    people: list[PersonResponse] = Field(default_factory=list)
    total_at_organisation: int = 0
    returned: int = 0
