from typing import Annotated, ClassVar, Literal
from urllib.parse import quote

from fastmcp import Context
from fastmcp.tools import tool
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.backstop_client import BackstopApiResourceDocument
from backstop_mcp.features.custom_fields import glossary_meta
from backstop_mcp.features.data_hygiene import (
    AsOf,
    DepartedContactResponse,
    EmploymentStatus,
    EntityRelationshipInclude,
    ProvenanceFields,
    as_of_response,
    departed_response,
    entity_relationships,
    extract_as_of,
)
from backstop_mcp.features.entity_types import EntityType
from backstop_mcp.features.party_resolver import (
    PartyAmbiguousResponse,
    ResolvedPartyResponse,
    party_response,
    resolve_party,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved
from backstop_mcp.server.runtime import get_backstop_client, get_employment_index_factory
from backstop_mcp.server.tools.results import tool_result


class PersonAttributes(ProvenanceFields):
    """Person resource attributes; extras preserved for the tool payload."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow", populate_by_name=True)

    name: str | None = None


class PersonResolvedResponse(BaseModel):
    """`get_person` once the person was found and fetched.

    Always returns the person when resolved. When employment has ended anywhere, `departed` is
    true and `departures` carries one entry per organization the person has left, each already
    identifying its own `organization_id` — relay every entry to the user and do not present the
    person as a current contact at any of those organizations unless they asked for historical
    contacts.
    """

    status: Literal["resolved"] = "resolved"
    person: PersonAttributes
    resolved: ResolvedPartyResponse
    as_of: AsOf | None = None
    departed: bool = False
    departures: list[DepartedContactResponse] = Field(default_factory=list)


type GetPersonResponse = PartyAmbiguousResponse | NotFoundResponse | PersonResolvedResponse


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    meta=glossary_meta(EntityType.PEOPLE),
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
) -> CallToolResult:
    """Fetch one Backstop person by trusted Party ID or by name/email search.

    Never invent or guess a party_id. Only pass a party_id that was previously returned
    by this server's resolve echo (`id` / `search_type` / `name`), and pass that echo's
    `search_type` too when it is not `people`. Otherwise pass `search` (person name or
    email) and let the server resolve it.
    Exactly one of party_id or search must be provided.

    Side-loads entityRelationships and their relationship types on the same GET (no extra round
    trip). When the CRM links the person to an organization as a past employee, or an employment
    endDate has passed, `departed` is true — always relay `departed` / `departures` to the
    user; do not present a departed person as a current contact unless they explicitly asked for
    historical contacts.

    `as_of` is plain provenance (modifiedTimestamp / modifiedBy). Relay it; do not treat
    record age as a staleness verdict.

    When the custom-field glossary on this tool is truncated or missing, call
    `list_custom_fields` with entity_type=people.
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
        return tool_result(unresolved_party_response(result))

    party = result.value
    # Quick-search for people uses the shared PERSON_* types, so a hit may be a
    # contact/employee; follow `party.search_type` instead of hard-coding `/people`.
    path = f"/{party.search_type}/{quote(party.id, safe='')}"
    document = await client.get(
        path,
        params={"include": EntityRelationshipInclude.for_employment()},
        schema=BackstopApiResourceDocument[PersonAttributes],
    )
    attributes = document.data.attributes
    index = get_employment_index_factory().index(
        **entity_relationships(document),
    )
    departures: list[DepartedContactResponse] = []
    for record in index.pairs(status=EmploymentStatus.FORMER):
        assert record.departure is not None, (
            "EmploymentIndex invariant: a FORMER record always carries departure evidence"
        )
        response = departed_response(record.departure)
        assert response is not None
        departures.append(response)

    return tool_result(
        PersonResolvedResponse(
            person=attributes,
            resolved=party_response(
                party, attributes=attributes.model_dump(by_alias=True, exclude_none=True)
            ),
            as_of=as_of_response(extract_as_of(attributes)),
            departed=bool(departures),
            departures=departures,
        )
    )
