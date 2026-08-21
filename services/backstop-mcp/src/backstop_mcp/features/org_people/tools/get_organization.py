from collections.abc import Sequence
from typing import Annotated, Literal

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client
from backstop_mcp.features.custom_fields import (
    CustomFieldsService,
    ResolvedCustomFieldValueResponse,
    get_custom_fields_service,
)
from backstop_mcp.features.data_hygiene import AsOfResponse
from backstop_mcp.features.includes import OrganizationInclude, OrganizationIncludesResponse
from backstop_mcp.features.org_people import OrganizationRecordResponse, fetch_organization
from backstop_mcp.features.party_resolver import (
    PartyAmbiguousResponse,
    ResolvedPartyResponse,
    resolve_party,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved
from backstop_mcp.models import OmitNoneModel, published_output_schema


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


type GetOrganizationResponse = (
    PartyAmbiguousResponse | NotFoundResponse | OrganizationResolvedResponse
)


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    output_schema=published_output_schema(GetOrganizationResponse),
)
async def get_organization(
    ctx: Context,
    party_id: Annotated[
        str | None,
        Field(
            description=(
                "Trusted Backstop organization Party ID from a prior resolve echo "
                "(`id` / `search_type` / `name`). Never invent or guess. Exactly one of "
                "`party_id` or `search` must be provided."
            ),
        ),
    ] = None,
    search: Annotated[
        str | None,
        Field(
            description=(
                "Organization name or email to resolve when no trusted `party_id` is "
                "available. Exactly one of `party_id` or `search` must be provided."
            ),
        ),
    ] = None,
    search_type: Annotated[
        Literal["organizations"] | None,
        Field(
            description=(
                "Echo `search_type` from a prior resolve. This tool only reads organizations; "
                "omit it or pass `organizations`. A person/contact/employee echo belongs on "
                "get_person, not here."
            ),
        ),
    ] = None,
    include: Annotated[
        Sequence[OrganizationInclude],
        Field(
            description=(
                "Related records to side-load on the same request, returned under `included`: "
                "`locations` for the postal addresses on file with their per-address phone "
                "numbers; `email_addresses` for the organization's address book, with retired "
                "addresses flagged rather than hidden; `primary_contact` for the person "
                "Backstop names as the main point of contact; `representative` for the "
                "colleague at our own firm who owns the relationship, which is not a way to "
                "contact the organization. Omit to return only the organization's own fields."
            ),
        ),
    ] = (),
    custom_field_tabs: Annotated[
        Sequence[str],
        Field(
            description=(
                "Layout tab names whose custom-field values to keep. Case-insensitive. "
                "Combined with other custom-field filters with AND. Omit to keep every tab."
            ),
        ),
    ] = (),
    custom_field_groups: Annotated[
        Sequence[str],
        Field(
            description=(
                "Layout group names whose custom-field values to keep. Case-insensitive. "
                "Combined with other custom-field filters with AND. Omit to keep every group."
            ),
        ),
    ] = (),
    custom_field_group_ids: Annotated[
        Sequence[int],
        Field(
            description=(
                "Layout group ids whose custom-field values to keep, as published on "
                "definitions and by list_custom_field_groups. Combined with other "
                "custom-field filters with AND. Omit to keep every group."
            ),
        ),
    ] = (),
    custom_field_definition_ids: Annotated[
        Sequence[str],
        Field(
            description=(
                "Custom-field definition ids whose values to keep. Combined with other "
                "custom-field filters with AND. Omit to keep every definition."
            ),
        ),
    ] = (),
    custom_field_names: Annotated[
        Sequence[str],
        Field(
            description=(
                "Custom-field names whose values to keep. Case-insensitive. Duplicate names "
                "stay distinct because each value keeps its definition id. Combined with other "
                "custom-field filters with AND. Omit to keep every name."
            ),
        ),
    ] = (),
    client: BackstopClient = Depends(get_backstop_client),
    custom_fields: CustomFieldsService = Depends(get_custom_fields_service),
) -> GetOrganizationResponse:
    """Fetch one Backstop organization by trusted Party ID or by name/email search.

    Never invent or guess a party_id. Only pass a party_id that was previously returned
    by this server's resolve echo (`id` / `search_type` / `name`). Echo `search_type` when
    you have it; this tool accepts only `organizations`. Otherwise pass `search`
    (organization name or email) and let the server resolve it.
    Exactly one of party_id or search must be provided.

    Pass `include` to side-load related records on the same request — addresses, the email
    address book, the primary contact, the representative. They come back under `included`,
    where a requested list is `[]` when there is nothing on file; omit `include` and only the
    organization's own fields are returned. `representative` is the colleague at our own firm
    who owns the relationship, not a way to contact the organization.

    Responses include `as_of` provenance when Backstop provides modifiedTimestamp/modifiedBy.
    Relay that provenance to the user; do not treat record age as a staleness verdict.

    Custom-field values are returned under `custom_field_values`, joined to the catalog
    (definition id, name, layout, group, type, and value). Fields may belong to the
    organization or to the shared party catalog; this tool joins both. Pass optional
    `custom_field_tabs`, `custom_field_groups`, `custom_field_group_ids`,
    `custom_field_definition_ids`, or `custom_field_names` to slice that list — filters AND
    together, and name/tab/group matching is case-insensitive. Values that are not in a
    field's current option list are kept and flagged. ENTITY-typed values are a resolvable
    reference (id, resource type, optional link); when the resource is a party collection,
    `search_type` is included so it can be echoed into `get_person` or `get_organization`.
    Call `list_custom_fields` for the catalog itself. `numberOfEmployees` is not a roster —
    use `get_people_for_party` for the people Backstop actually links to this organization.
    """
    result = await resolve_party(
        ctx,
        client,
        search_type=search_type if search_type is not None else "organizations",
        party_id=party_id,
        search=search,
    )
    if not isinstance(result, Resolved):
        return unresolved_party_response(result)

    party = result.value
    fetched = await fetch_organization(
        client,
        party_id=party.id,
        include=include,
    )
    record, stored_values = custom_fields.take_stored_values(
        fetched.organization.model_dump(by_alias=True)
    )
    organization = OrganizationRecordResponse.model_validate(record)
    custom_field_values = await custom_fields.resolve_values(
        client,
        stored_values,
        tabs=custom_field_tabs,
        groups=custom_field_groups,
        group_ids=custom_field_group_ids,
        definition_ids=custom_field_definition_ids,
        names=custom_field_names,
    )
    return OrganizationResolvedResponse(
        organization=organization,
        resolved=ResolvedPartyResponse.from_party(
            party,
            attributes=organization.model_dump(by_alias=True, exclude_none=True),
        ),
        as_of=AsOfResponse.from_attributes(organization),
        included=fetched.included,
        custom_field_values=custom_field_values,
    )
