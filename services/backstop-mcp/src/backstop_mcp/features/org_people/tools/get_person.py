import asyncio
from collections.abc import Sequence
from typing import Annotated, Literal

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.custom_fields import (
    CustomFieldFilters,
    CustomFieldsService,
    ResolvedCustomFieldValueResponse,
    get_custom_fields_service,
)
from backstop_mcp.features.data_hygiene import (
    AsOfResponse,
    EmploymentIndexFactory,
    EmploymentLinkResponse,
    get_employment_index_factory,
)
from backstop_mcp.features.includes import PersonInclude, PersonIncludesResponse
from backstop_mcp.features.org_people import PersonRecordResponse, fetch_person
from backstop_mcp.features.party_resolver import (
    PartyAmbiguousResponse,
    ResolvedPartyResponse,
    resolve_party,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved
from backstop_mcp.models import CoercedId, OmitNoneModel, coerce_ids, published_output_schema


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


type GetPersonResponse = PartyAmbiguousResponse | NotFoundResponse | PersonResolvedResponse


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    output_schema=published_output_schema(GetPersonResponse),
)
async def get_person(
    ctx: Context,
    party_id: Annotated[
        str | None,
        Field(
            description=(
                "Trusted Backstop person Party ID from a prior resolve echo "
                "(`id` / `search_type` / `name`). Never invent or guess. Exactly one of "
                "`party_id` or `search` must be provided."
            ),
        ),
    ] = None,
    search: Annotated[
        str | None,
        Field(
            description=(
                "Person name or email to resolve when no trusted `party_id` is available. "
                "Exactly one of `party_id` or `search` must be provided."
            ),
        ),
    ] = None,
    search_type: Annotated[
        Literal["people", "contacts", "employees"] | None,
        Field(
            description=(
                "Collection to resolve against. Echo `search_type` from a prior resolve "
                "when retrying with `party_id` — a contact or employee id is not a people "
                "id. Defaults to people."
            ),
        ),
    ] = None,
    include: Annotated[
        Sequence[PersonInclude],
        Field(
            description=(
                "Related records to side-load on the same request, returned under `included`: "
                "`locations` for the postal addresses on file with their per-address phone "
                "numbers; `email_addresses` for the person's address book, with retired "
                "addresses flagged rather than hidden; `company` for the organization they "
                "work at; `representative` for the colleague at our own firm who owns the "
                "relationship, which is not a way to contact the person. Omit to return only "
                "the person's own fields."
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
        Sequence[CoercedId],
        Field(
            description=(
                "Custom-field definition ids whose values to keep, as published on "
                "list_custom_fields `id` and on `custom_field_values[].definition_id`. "
                "JSON numbers are accepted. Combined with other custom-field filters with "
                "AND. Omit to keep every definition."
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
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    custom_fields: CustomFieldsService = Depends(get_custom_fields_service),
    employment_index_factory: EmploymentIndexFactory = Depends(get_employment_index_factory),
) -> GetPersonResponse:
    """Fetch one Backstop person by trusted Party ID or by name/email search.

    Never invent or guess a party_id. Only pass a party_id that was previously returned
    by this server's resolve echo (`id` / `search_type` / `name`), and pass that echo's
    `search_type` too when it is not `people`. Otherwise pass `search` (person name or
    email) and let the server resolve it.
    Exactly one of party_id or search must be provided.

    Side-loads entityRelationships and their relationship types on the same GET (no extra round
    trip). `employments` lists every current and former organization link — always relay those
    entries; do not present a person as a current contact at an organization whose link has
    `status="former"` unless they explicitly asked for historical contacts.

    Pass `include` to side-load related records on that same GET — addresses, the email address
    book, their organization, the representative. They come back under `included`, where a
    requested list is `[]` when there is nothing on file; omit `include` and only the person's
    own fields are returned. `representative` is the colleague at our own firm who owns the
    relationship, not a way to contact the person.

    `as_of` is plain provenance (modifiedTimestamp / modifiedBy). Relay it; do not treat
    record age as a staleness verdict.

    Custom-field values are returned under `custom_field_values`, joined to the catalog
    (definition id, name, layout, group, type, and value). Fields may belong to the person
    or to the shared party catalog; this tool joins both. Pass optional `custom_field_tabs`,
    `custom_field_groups`, `custom_field_group_ids`, `custom_field_definition_ids`, or
    `custom_field_names` to slice that list — filters AND together, and name/tab/group
    matching is case-insensitive. Values that are not in a field's current option list are
    kept and flagged. ENTITY-typed values are a resolvable reference (id, resource type,
    optional link); when the resource is a party collection, `search_type` is included so
    it can be echoed into `get_person` or `get_organization`. Call `list_custom_fields`
    for the catalog itself.
    """
    result = await resolve_party(
        ctx,
        client,
        search_type=search_type if search_type is not None else "people",
        party_id=party_id,
        search=search,
    )
    if not isinstance(result, Resolved):
        return unresolved_party_response(result)

    party = result.value
    fetched, _ = await asyncio.gather(
        fetch_person(
            client,
            employment_index_factory,
            search_type=party.search_type,
            party_id=party.id,
            include=include,
        ),
        custom_fields.load_catalog(client),
    )
    person = fetched.person
    custom_field_values = await custom_fields.join_values(
        client,
        person.regular_custom_field_values,
        filters=CustomFieldFilters(
            tabs=tuple(custom_field_tabs),
            groups=tuple(custom_field_groups),
            group_ids=tuple(custom_field_group_ids),
            definition_ids=coerce_ids(custom_field_definition_ids),
            names=tuple(custom_field_names),
        ),
    )
    return PersonResolvedResponse(
        person=person,
        resolved=ResolvedPartyResponse.from_party(
            party, attributes=person.model_dump(by_alias=True, exclude_none=True)
        ),
        as_of=AsOfResponse.from_attributes(person),
        employments=fetched.employments,
        included=fetched.included,
        custom_field_values=custom_field_values,
    )
