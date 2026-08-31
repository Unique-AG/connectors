"""MCP-facing person and organization records, the people listing, and the tool wraps."""

from typing import ClassVar, Literal, Self

from pydantic import ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema

from backstop_mcp.features.custom_fields import (
    RegularCustomFieldValues,
    ResolvedCustomFieldValueResponse,
)
from backstop_mcp.features.data_hygiene import (
    AsOfResponse,
    EmploymentLinkResponse,
    ProvenanceAttributes,
)
from backstop_mcp.features.includes import OrganizationIncludesResponse, PersonIncludesResponse
from backstop_mcp.features.org_people.api_responses import (
    EmployeeResource,
    OrganizationAttributes,
    PersonAttributes,
)
from backstop_mcp.features.party_resolver import ResolvedPartyResponse
from backstop_mcp.models import OmitNoneModel

__all__ = [
    "OrgPeopleResolvedResponse",
    "OrganizationRecordResponse",
    "OrganizationResolvedResponse",
    "PartyOrgPeopleResponse",
    "PartyOrganizationResponse",
    "PartyPersonResponse",
    "PersonAtOrganizationResponse",
    "PersonRecordResponse",
    "PersonResolvedResponse",
]


def _record_fields(attributes: PersonAttributes | OrganizationAttributes) -> dict[str, object]:
    """Known fields under their own names, with the instance's own keys passed through.

    `passthrough()` comes first so a wire key that collides with a modelled one loses to the
    modelled value rather than shadowing it.
    """
    return {
        **attributes.passthrough(),
        "name": attributes.name,
        "regular_custom_field_values": attributes.regular_custom_field_values,
        "modified_timestamp": attributes.modified_timestamp,
        "modified_by": attributes.modified_by,
    }


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
        description=(
            "Wire dump of regularCustomFieldValues used to resolve published "
            "custom_field_values; omitted from the tool payload."
        ),
    )

    @classmethod
    def from_attributes(cls, attributes: PersonAttributes) -> Self:
        return cls.model_validate(_record_fields(attributes))


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
        description=(
            "Wire dump of regularCustomFieldValues used to resolve published "
            "custom_field_values; omitted from the tool payload."
        ),
    )

    @classmethod
    def from_attributes(cls, attributes: OrganizationAttributes) -> Self:
        return cls.model_validate(_record_fields(attributes))


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
    def from_employment(cls, employment: EmploymentLinkResponse) -> Self:
        """A row with no `/employees` card — a former person, who is not on that walk."""
        return cls(
            id=employment.person_id,
            search_type=employment.person_type,
            employment=employment,
        )

    @classmethod
    def from_resource(cls, employment: EmploymentLinkResponse, resource: EmployeeResource) -> Self:
        card = resource.attributes
        return cls(
            id=employment.person_id,
            search_type=employment.person_type,
            name=card.name,
            job_title=card.job_title,
            email=card.email,
            phone=card.phone,
            company_name=card.company_name,
            categories=card.categories,
            employment=employment,
        )


class PartyPersonResponse(OmitNoneModel):
    """`GetPersonQuery`'s answer: the record, its employment links, includes, custom fields."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    person: PersonRecordResponse = Field(description="The person's own Backstop attributes.")
    employments: list[EmploymentLinkResponse] = Field(
        default_factory=list,
        description="Every current and former organization link the CRM records.",
    )
    included: PersonIncludesResponse | None = Field(
        default=None, description="Side-loads for the requested includes, when any were asked for."
    )
    custom_field_values: list[ResolvedCustomFieldValueResponse] = Field(
        default_factory=list,
        description="Custom-field values on this record, joined to the catalog and filtered.",
    )


class PartyOrganizationResponse(OmitNoneModel):
    """`GetOrganizationQuery`'s answer: the record, its includes, and its custom fields."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    organization: OrganizationRecordResponse = Field(
        description="The organization's own Backstop attributes."
    )
    included: OrganizationIncludesResponse | None = Field(
        default=None, description="Side-loads for the requested includes, when any were asked for."
    )
    custom_field_values: list[ResolvedCustomFieldValueResponse] = Field(
        default_factory=list,
        description="Custom-field values on this record, joined to the catalog and filtered.",
    )


class PartyOrgPeopleResponse(OmitNoneModel):
    """`GetPeopleForOrganizationQuery`'s answer: the rows kept, and what was dropped."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    people: tuple[PersonAtOrganizationResponse, ...] = Field(
        description="People the employment index ties to this organization."
    )
    former_omitted: int = Field(
        default=0,
        description="Former-employment links dropped because `include_former` is false.",
    )
    people_omitted: int = Field(
        default=0, description="Matching people dropped because the per-call cap was reached."
    )


class PersonResolvedResponse(OmitNoneModel):
    """`get_person` once the person was found and fetched.

    Always returns the person when resolved. `employments` lists every current and former
    organization link the CRM records for this person — relay each entry, and do not present the
    person as a current contact at any organization marked `status="former"` unless they asked
    for historical contacts.
    """

    status: Literal["resolved"] = Field(
        default="resolved",
        description="Always 'resolved': the person was found and fetched.",
    )
    person: PersonRecordResponse = Field(
        description=(
            "The person's own Backstop attributes. Known keys (`name`, `modifiedTimestamp`, "
            "`modifiedBy`) are documented; other keys are this instance's fields passed "
            "through unchanged. Custom-field values are under `custom_field_values`, not on "
            "this record."
        )
    )
    resolved: ResolvedPartyResponse = Field(
        description=(
            "The identity this call settled on. Echo `id` / `search_type` / `name` as "
            "`party_id` later — never invent them."
        )
    )
    as_of: AsOfResponse | None = Field(
        default=None,
        description=(
            "When and by whom the person record was last saved. Omitted when unknown. "
            "Relay this; do not treat age as a staleness verdict."
        ),
    )
    employments: list[EmploymentLinkResponse] = Field(
        default_factory=list,
        description=(
            "Every current and former organization link. Do not present the person as a "
            "current contact at any organization whose `status` is 'former' unless they "
            "asked for historical contacts."
        ),
    )
    included: PersonIncludesResponse | None = Field(
        default=None,
        description=(
            "The related records asked for through `include`, side-loaded on the same request. "
            "Absent when no include was asked for."
        ),
    )
    custom_field_values: list[ResolvedCustomFieldValueResponse] = Field(
        default_factory=list,
        description=(
            "Custom-field values on this record, joined to the catalog (definition id, name, "
            "layout, group, type, and value). Fields may belong to the person or to the shared "
            "party catalog. Empty when the record has none or the catalog could not be loaded. "
            "Slice with the custom_field_* filters rather than fetching again."
        ),
    )


class OrganizationResolvedResponse(OmitNoneModel):
    """`get_organization`'s response once the organization was found and fetched.

    `organization` holds the record's own fields (the JSON:API resource's `attributes`) — not
    the enclosing document, whose `type`/`id` are already echoed under `resolved`.
    `as_of` is plain provenance (`modifiedTimestamp` / `modifiedBy`); relay it, do not treat
    age as a staleness verdict.
    """

    status: Literal["resolved"] = Field(
        default="resolved",
        description="Always 'resolved': the organization was found and fetched.",
    )
    organization: OrganizationRecordResponse = Field(
        description=(
            "The organization's own Backstop attributes. Known keys (`name`, "
            "`modifiedTimestamp`, `modifiedBy`) are documented; other keys are this "
            "instance's fields passed through unchanged. Custom-field values are under "
            "`custom_field_values`, not on this record."
        )
    )
    resolved: ResolvedPartyResponse = Field(
        description=(
            "The identity this call settled on. Echo `id` / `search_type` / `name` as "
            "`party_id` later — never invent them."
        )
    )
    as_of: AsOfResponse | None = Field(
        default=None,
        description=(
            "When and by whom the organization record was last saved. Omitted when "
            "unknown. Relay this; do not treat age as a staleness verdict."
        ),
    )
    included: OrganizationIncludesResponse | None = Field(
        default=None,
        description=(
            "The related records asked for through `include`, side-loaded on the same request. "
            "Absent when no include was asked for."
        ),
    )
    custom_field_values: list[ResolvedCustomFieldValueResponse] = Field(
        default_factory=list,
        description=(
            "Custom-field values on this record, joined to the catalog (definition id, name, "
            "layout, group, type, and value). Fields may belong to the organization or to the "
            "shared party catalog. Empty when the record has none or the catalog could not be "
            "loaded. Slice with the custom_field_* filters rather than fetching again."
        ),
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
    def from_people(
        cls,
        *,
        resolved: ResolvedPartyResponse,
        people: tuple[PersonAtOrganizationResponse, ...],
        former_omitted: int,
        people_omitted: int,
    ) -> Self:
        hint = None
        if former_omitted:
            if not people:
                hint = (
                    "No current employees were returned; "
                    f"{former_omitted} former-employment link(s) were omitted. "
                    "Pass include_former=true rather than treating this as no people on file."
                )
            else:
                hint = (
                    f"{former_omitted} former-employment link(s) were omitted. "
                    "Pass include_former=true to include them."
                )
        return cls(
            resolved=resolved,
            people=people,
            former_omitted=former_omitted,
            people_omitted=people_omitted,
            include_former_hint=hint,
        )
