"""MCP-facing person and organization records, and the people-at-organization listing."""

from typing import ClassVar, Literal, Self

from pydantic import ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema

from backstop_mcp.features.custom_fields import RegularCustomFieldValues
from backstop_mcp.features.data_hygiene import EmploymentLinkResponse, ProvenanceAttributes
from backstop_mcp.features.org_people.internal_dto import (
    OrgPeopleListingDto,
    PersonAtOrganizationDto,
)
from backstop_mcp.features.party_resolver import ResolvedPartyResponse
from backstop_mcp.models import OmitNoneModel


class PersonRecordResponse(OmitNoneModel, ProvenanceAttributes):
    """Person resource attributes; extras preserved for the tool payload."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow", populate_by_name=True)

    name: str | None = Field(
        default=None,
        description="Display name as Backstop stores it, usually 'Last, First'.",
    )
    regular_custom_field_values: SkipJsonSchema[RegularCustomFieldValues] = Field(
        default_factory=list,
        alias="regularCustomFieldValues",
        exclude=True,
    )


class OrganizationRecordResponse(OmitNoneModel, ProvenanceAttributes):
    """Shape of an organization resource's `attributes` in `get_organization`'s response.

    `extra="allow"` so unrecognized Backstop fields survive on the typed payload, and so
    `AsOfResponse.from_attributes` can read provenance from the model rather than string keys
    on a dump.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow", populate_by_name=True)

    name: str | None = Field(
        default=None,
        description="Organization name as Backstop stores it.",
    )
    regular_custom_field_values: SkipJsonSchema[RegularCustomFieldValues] = Field(
        default_factory=list,
        alias="regularCustomFieldValues",
        exclude=True,
    )


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
    categories: tuple[str, ...] | None = Field(
        default=None,
        description="CRM categories on this person — investor type, role, or similar labels.",
    )
    employment: EmploymentLinkResponse = Field(
        description=(
            "Employment at *this* organization, from `EmploymentIndex`: `status` is `current` "
            "or `former`. Do not present a `former` row as a live contact unless they asked "
            "for historical contacts."
        )
    )

    @classmethod
    def from_person(cls, row: PersonAtOrganizationDto) -> Self:
        card = row.card
        employment = row.employment
        return cls(
            id=employment.person_id,
            search_type=employment.person_type,
            name=None if card is None else card.name,
            job_title=None if card is None else card.job_title,
            email=None if card is None else card.email,
            phone=None if card is None else card.phone,
            company_name=None if card is None else card.company_name,
            categories=None if card is None else card.categories,
            employment=employment,
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

    @classmethod
    def from_listing(cls, listing: OrgPeopleListingDto, *, resolved: ResolvedPartyResponse) -> Self:
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
        return cls(
            resolved=resolved,
            people=tuple(PersonAtOrganizationResponse.from_person(row) for row in listing.people),
            former_omitted=listing.former_omitted,
            people_omitted=listing.people_omitted,
            include_former_hint=hint,
        )
