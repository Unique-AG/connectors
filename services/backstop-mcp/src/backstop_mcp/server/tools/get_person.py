from typing import ClassVar, Literal
from urllib.parse import quote

from fastmcp import Context
from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import (
    BackstopApiDocument,
    included_for_relationship,
    included_of_type,
    single_resource,
)
from backstop_mcp.coerce import as_clean_str
from backstop_mcp.features.data_hygiene import (
    ENTITY_RELATIONSHIP_TYPES_RESOURCE,
    ENTITY_RELATIONSHIPS_INCLUDE,
    ENTITY_RELATIONSHIPS_RELATIONSHIP,
    AsOfEcho,
    DepartedContactEcho,
    as_of_echo,
    departed_echo,
    extract_as_of,
)
from backstop_mcp.features.party_resolver import (
    PartyAmbiguousResponse,
    ResolvedParty,
    ResolvedPartyEcho,
    party_echo,
    resolve_party,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved
from backstop_mcp.server.runtime import get_backstop_client, get_departed_contact_detector


class PersonAttributes(BaseModel):
    """Person resource attributes; extras preserved for the tool payload dump."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow")

    name: str | None = None


class PersonResolvedResponse(BaseModel):
    """`get_person` once the person was found and fetched.

    Always returns the person when resolved. When employment has ended, `departed` is true and
    `departed_detail` carries the hard signal — relay both to the user and do not present the
    person as a current contact unless they asked for historical contacts.
    """

    status: Literal["resolved"] = "resolved"
    person: dict[str, object]
    resolved: ResolvedPartyEcho
    as_of: AsOfEcho | None = None
    departed: bool = False
    departed_detail: DepartedContactEcho | None = None


type GetPersonResponse = PartyAmbiguousResponse | NotFoundResponse | PersonResolvedResponse


async def get_person(
    ctx: Context,
    party_id: str | None = None,
    search: str | None = None,
) -> GetPersonResponse:
    """Fetch one Backstop person by trusted Party ID or by name/email search.

    Never invent or guess a party_id. Only pass a party_id that was previously returned
    by this server's resolve echo (`id` / `type` / `name`). Otherwise pass `search`
    (person name or email) and let the server resolve it.
    Exactly one of party_id or search must be provided.

    Side-loads entityRelationships and their relationship types on the same GET (no extra round
    trip). When the CRM links the person to an organization as a past employee, or an employment
    endDate has passed, `departed` is true — always relay `departed` / `departed_detail` to the
    user; do not present a departed person as a current contact unless they explicitly asked for
    historical contacts.

    `as_of` is plain provenance (modifiedTimestamp / modifiedBy). Relay it; do not treat
    record age as a staleness verdict.
    """
    client = await get_backstop_client()
    result = await resolve_party(
        ctx,
        client,
        search_type="people",
        party_id=party_id,
        search=search,
    )
    if not isinstance(result, Resolved):
        return unresolved_party_response(result)

    party = result.value
    path = f"/people/{quote(party.id, safe='')}"
    document = await client.get(
        path,
        params={"include": ENTITY_RELATIONSHIPS_INCLUDE},
        schema=BackstopApiDocument[PersonAttributes],
    )
    resource = single_resource(document, path=path)
    attributes = resource.attributes.model_dump(exclude_none=True) if resource is not None else {}
    resolved = party if party.name is not None else _with_name(party, attributes)
    relationships: list[dict[str, object]] = (
        included_for_relationship(document, resource, ENTITY_RELATIONSHIPS_RELATIONSHIP)
        if resource is not None
        else []
    )
    # Selected by resource type, not followed from the person: the nested include's types are
    # linked from the relationships, so nothing on the person points at them.
    relationship_types = included_of_type(document, ENTITY_RELATIONSHIP_TYPES_RESOURCE)

    departed = get_departed_contact_detector().verify(
        relationships=relationships,
        relationship_types=relationship_types,
    )

    return PersonResolvedResponse(
        person=attributes,
        resolved=party_echo(resolved),
        as_of=as_of_echo(extract_as_of(attributes)),
        departed=departed is not None,
        departed_detail=departed_echo(departed),
    )


def _with_name(party: ResolvedParty, attributes: dict[str, object]) -> ResolvedParty:
    name = as_clean_str(attributes.get("name"))
    if name is None:
        first = as_clean_str(attributes.get("firstName")) or as_clean_str(
            attributes.get("first_name")
        )
        last = as_clean_str(attributes.get("lastName")) or as_clean_str(attributes.get("last_name"))
        parts = [part for part in (first, last) if part is not None]
        name = " ".join(parts) if parts else None
    if name is None:
        return party
    return ResolvedParty(id=party.id, type=party.type, name=name)
