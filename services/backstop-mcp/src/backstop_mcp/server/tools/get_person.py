from collections.abc import Sequence
from typing import Annotated, ClassVar, Literal
from urllib.parse import quote

from fastmcp import Context
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import ConfigDict, Field

from backstop_mcp.backstop_client import BackstopApiResourceDocument
from backstop_mcp.features.data_hygiene import (
    AsOf,
    EmploymentLinkResponse,
    EntityRelationshipInclude,
    ProvenanceFields,
    as_of_response,
    entity_relationships,
    extract_as_of,
)
from backstop_mcp.features.includes import (
    PersonInclude,
    PersonIncludesResponse,
    include_plan,
)
from backstop_mcp.features.party_resolver import (
    PartyAmbiguousResponse,
    ResolvedPartyResponse,
    party_response,
    resolve_party,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved
from backstop_mcp.models import OmitNoneModel, published_output_schema
from backstop_mcp.server.runtime import get_backstop_client, get_employment_index_factory


class PersonAttributes(OmitNoneModel, ProvenanceFields):
    """Person resource attributes; extras preserved for the tool payload."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow", populate_by_name=True)

    name: str | None = Field(
        default=None,
        description="Display name as Backstop stores it, usually 'Last, First'.",
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
    person: PersonAttributes = Field(
        description=(
            "The person's own Backstop attributes. Known keys (`name`, `modifiedTimestamp`, "
            "`modifiedBy`) are documented; other keys are this instance's fields passed "
            "through unchanged, including custom field values. Call `list_custom_fields` "
            "for what those mean."
        )
    )
    resolved: ResolvedPartyResponse = Field(
        description=(
            "The identity this call settled on. Echo `id` / `search_type` / `name` as "
            "`party_id` later — never invent them."
        )
    )
    as_of: AsOf | None = Field(
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

    When you need custom field names for this person, call `list_custom_fields` with
    entity_types including people.
    """
    client = await get_backstop_client()
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
    # Quick-search for people uses the shared PERSON_* types, so a hit may be a
    # contact/employee; follow `party.search_type` instead of hard-coding `/people`.
    path = f"/{party.search_type}/{quote(party.id, safe='')}"
    plan = include_plan(PersonIncludesResponse, requested=include)
    # `plan.param` is empty when nothing was requested, so join only the non-empty parts.
    include_param = ",".join(
        part for part in (EntityRelationshipInclude.for_employment(), plan.param) if part
    )
    document = await client.get(
        path,
        params={"include": include_param} if include_param else None,
        schema=BackstopApiResourceDocument[PersonAttributes],
    )
    attributes = document.require_data(path=path).attributes
    index = get_employment_index_factory().index(**entity_relationships(document))

    return PersonResolvedResponse(
        person=attributes,
        resolved=party_response(
            party, attributes=attributes.model_dump(by_alias=True, exclude_none=True)
        ),
        as_of=as_of_response(extract_as_of(attributes)),
        employments=index.links(),
        included=plan.project(document=document) if plan.planned else None,
    )
