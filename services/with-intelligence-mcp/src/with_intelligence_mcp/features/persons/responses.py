from typing import Self

from pydantic import Field

from with_intelligence_mcp.features.persons.api_responses import (
    PersonExtendedAttributes,
    PersonRoleAttributes,
)
from with_intelligence_mcp.models import OmitNoneModel


class PersonResponse(OmitNoneModel):
    """One contact, as their role at the investor asked about — not their whole career."""

    id: int = Field(description="With Intelligence person identifier.", examples=[650889])
    name: str | None = Field(
        default=None, description="Person's full name.", examples=["Jordan Smith"]
    )
    job_title: str | None = Field(
        default=None,
        description="Person's title at this investor.",
        examples=["Chief Investment Officer"],
    )
    seniority: str | None = Field(
        default=None,
        description=(
            "With Intelligence's seniority band. The closest thing to a decision-maker signal."
        ),
        examples=["C-Suite"],
    )
    specialisms: list[str] | None = Field(
        default=None,
        description="Investment areas this person covers.",
        examples=[["Hedge Funds", "Private Equity"]],
    )
    email: str | None = Field(default=None, description="Primary work email for this role.")
    phone: str | None = Field(
        default=None, description="Primary or office phone number for this role."
    )
    linkedin: str | None = Field(
        default=None, description="LinkedIn profile URL recorded for the person."
    )
    biography: str | None = Field(
        default=None, description="With Intelligence biography for the person."
    )
    is_main_contact: bool | None = Field(
        default=None, description="Flagged by With Intelligence as the main contact here."
    )
    is_current: bool | None = Field(
        default=None,
        description=(
            "False when the role has an end date — they have left. Do not write to a former "
            "contact without saying so."
        ),
    )
    role_started: str | None = Field(
        default=None,
        description="Date the person started this role.",
        examples=["2022-01-15"],
    )
    role_ended: str | None = Field(
        default=None,
        description="Date the person left this role; absent for a current role.",
        examples=["2026-06-30"],
    )

    @classmethod
    def from_attributes(cls, attributes: PersonExtendedAttributes, *, organisation_id: int) -> Self:
        role = _role_at(attributes, organisation_id)
        return cls(
            id=attributes.id,
            name=attributes.full_name or attributes.name,
            job_title=role.job_title if role else None,
            seniority=role.seniority.name if role and role.seniority else None,
            specialisms=(
                [entry.name for entry in role.specialisms if entry.name] if role else None
            ),
            email=role.primary_email if role else None,
            phone=(role.primary_phone or role.office_phone) if role else None,
            linkedin=attributes.linked_in_url,
            biography=attributes.biography,
            is_main_contact=role.main_for_organisation if role else None,
            is_current=not role.end_date if role else None,
            role_started=role.start_date if role else None,
            role_ended=role.end_date if role else None,
        )


class PeopleForInvestorResponse(OmitNoneModel):
    """Contacts at one investor, with the caveat that the counts do not agree.

    `total_at_organisation` is what the person search reports; `contacts_on_investor_record` is
    what the investor record embeds. They differ — the record's list is longer — and which is
    authoritative is not documented, so both are reported rather than picking one.
    """

    investor_id: int = Field(description="With Intelligence investor identifier.")
    investor_name: str | None = Field(default=None, description="Resolved investor name.")
    people: list[PersonResponse] = Field(
        default_factory=list,
        description="People on the requested page, ordered by most recently updated.",
    )
    total_at_organisation: int = Field(
        default=0,
        description="Total people reported by the person search for this investor.",
    )
    contacts_on_investor_record: int | None = Field(
        default=None,
        description="Contact count embedded in the investor profile, which may differ.",
    )
    returned: int = Field(default=0, description="Number of people returned on this page.")
    page: int = Field(default=1, description="Page number represented by this response.")
    has_more: bool = Field(
        default=False, description="True when another page of people is available."
    )


def _role_at(
    attributes: PersonExtendedAttributes, organisation_id: int
) -> PersonRoleAttributes | None:
    matching = [
        role
        for role in attributes.person_roles
        if role.organisation is not None
        and organisation_id in (role.organisation.id, role.organisation.org_entity_id)
    ]
    if not matching:
        return None
    current = [role for role in matching if not role.end_date]
    return current[0] if current else max(matching, key=lambda role: role.end_date or "")
