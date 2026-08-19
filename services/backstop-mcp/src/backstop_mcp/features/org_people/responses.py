"""MCP-facing people-at-organization listing."""

from typing import Literal

from pydantic import Field

from backstop_mcp.features.data_hygiene import EmploymentLinkResponse
from backstop_mcp.features.org_people.internal_dto import (
    OrgPeopleListingDto,
    PersonAtOrganizationDto,
)
from backstop_mcp.features.party_resolver import ResolvedPartyResponse
from backstop_mcp.models import OmitNoneModel


class PersonAtOrganizationResponse(OmitNoneModel):
    """One person Backstop links to this organization, with employment status at that org."""

    id: str = Field(
        description=(
            "Backstop id of this person. Echo it as `party_id` on `get_person` with this "
            "row's `search_type` — never invent one."
        )
    )
    search_type: str = Field(
        description=(
            "Collection this person belongs to: people, contacts, or employees. Echo it with "
            "`id` — a contact or employee id is not a people id."
        )
    )
    name: str | None = Field(
        default=None,
        description="Display name as Backstop stores it, usually 'Last, First'.",
    )
    job_title: str | None = Field(
        default=None, description="Job title on the person record, when Backstop has one."
    )
    email: str | None = Field(
        default=None, description="Primary email on the person record, when Backstop has one."
    )
    phone: str | None = Field(
        default=None, description="Primary phone on the person record, when Backstop has one."
    )
    company_name: str | None = Field(
        default=None, description="Company name on the person record, when Backstop has one."
    )
    employment: EmploymentLinkResponse = Field(
        description=(
            "Employment at *this* organization, from `EmploymentIndex`: `status` is `current` "
            "or `former`. Do not present a `former` row as a live contact unless they asked "
            "for historical contacts."
        )
    )


class OrgPeopleResolvedResponse(OmitNoneModel):
    """`get_people_for_party` after the organization was found and its people listed."""

    status: Literal["resolved"] = Field(
        default="resolved",
        description="Always 'resolved': the organization was found and its people listed.",
    )
    resolved: ResolvedPartyResponse = Field(
        description=(
            "The identity this call settled on. Echo `id` / `search_type` / `name` as "
            "`party_id` later — never invent them."
        )
    )
    people: tuple[PersonAtOrganizationResponse, ...] = Field(
        description=(
            "People the CRM links to this organization through employment relationships. "
            "`numberOfEmployees` on the organization record is not this list and is often 0 "
            "while people are still on file. Each row's `employment` is the status at this "
            "organization. Call `get_person` for the full record."
        )
    )
    former_omitted: int = Field(
        description=(
            "How many former-employment links were dropped because `include_former` is false. "
            "Distinguishes an organization with no people from one whose only links are former."
        )
    )
    people_omitted: int = Field(
        default=0,
        description=(
            "How many matching people were listed but dropped because this organization "
            "exceeds the per-call cap. Greater than zero means `people` is a partial list."
        ),
    )
    include_former_hint: str | None = Field(
        default=None,
        description=(
            "Set when former employees were omitted. Pass `include_former=true` rather than "
            "treating an empty list as 'this organization has no people'."
        ),
    )


def person_at_organization_response(
    row: PersonAtOrganizationDto,
) -> PersonAtOrganizationResponse:
    card = row.card
    employment = row.employment
    return PersonAtOrganizationResponse(
        id=employment.person_id,
        search_type=employment.person_type,
        name=None if card is None else card.name,
        job_title=None if card is None else card.job_title,
        email=None if card is None else card.email,
        phone=None if card is None else card.phone,
        company_name=None if card is None else card.company_name,
        employment=employment,
    )


def org_people_response(
    *, resolved: ResolvedPartyResponse, listing: OrgPeopleListingDto
) -> OrgPeopleResolvedResponse:
    returned = len(listing.people)
    hint = None
    if listing.former_omitted:
        if returned == 0:
            hint = (
                "No current employees were returned; "
                f"{listing.former_omitted} former-employment link(s) were omitted. "
                "Pass include_former=true rather than treating this as no people on file."
            )
        else:
            hint = (
                f"{listing.former_omitted} former-employment link(s) were omitted. "
                "Pass include_former=true to include them."
            )
    return OrgPeopleResolvedResponse(
        resolved=resolved,
        people=tuple(person_at_organization_response(row) for row in listing.people),
        former_omitted=listing.former_omitted,
        people_omitted=listing.people_omitted,
        include_former_hint=hint,
    )
