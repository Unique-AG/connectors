from typing import ClassVar, Literal
from urllib.parse import quote

from fastmcp import Context
from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import BackstopApiDocument, single_resource
from backstop_mcp.coerce import as_clean_str
from backstop_mcp.features.data_hygiene import AsOfEcho, as_of_echo, extract_as_of
from backstop_mcp.features.party_resolver import (
    PartyAmbiguousResponse,
    ResolvedParty,
    ResolvedPartyEcho,
    party_echo,
    resolve_party,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved
from backstop_mcp.server.runtime import get_backstop_client


class OrganizationAttributes(BaseModel):
    """Shape of an organization resource's `attributes` in `get_organization`'s response.

    `extra="allow"` so unrecognized Backstop fields (e.g. `status`, `modifiedTimestamp`)
    survive the `model_dump(exclude_none=True)` round-trip that rebuilds the `organization`
    dict — and so `extract_as_of` can read provenance from the same dump.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow")

    name: str | None = None


class OrganizationResolvedResponse(BaseModel):
    """`get_organization`'s response once the organization was found and fetched.

    `organization` holds the record's own fields (the JSON:API resource's `attributes`) — not
    the enclosing document, whose `type`/`id` are already echoed under `resolved`.
    `as_of` is plain provenance (`modifiedTimestamp` / `modifiedBy`); relay it, do not treat
    age as a staleness verdict.
    """

    status: Literal["resolved"] = "resolved"
    organization: dict[str, object]
    resolved: ResolvedPartyEcho
    as_of: AsOfEcho | None = None


type GetOrganizationResponse = (
    PartyAmbiguousResponse | NotFoundResponse | OrganizationResolvedResponse
)


async def get_organization(
    ctx: Context,
    party_id: str | None = None,
    search: str | None = None,
) -> GetOrganizationResponse:
    """Fetch one Backstop organization by trusted Party ID or by name/email search.

    Never invent or guess a party_id. Only pass a party_id that was previously returned
    by this server's resolve echo (`id` / `type` / `name`). Otherwise pass `search`
    (organization name or email) and let the server resolve it.
    Exactly one of party_id or search must be provided.

    Responses include `as_of` provenance when Backstop provides modifiedTimestamp/modifiedBy.
    Relay that provenance to the user; do not treat record age as a staleness verdict.
    """
    client = await get_backstop_client()
    result = await resolve_party(
        ctx,
        client,
        search_type="organizations",
        party_id=party_id,
        search=search,
    )
    if not isinstance(result, Resolved):
        return unresolved_party_response(result)

    party = result.value
    path = f"/organizations/{quote(party.id, safe='')}"
    document = await client.get(path, schema=BackstopApiDocument[OrganizationAttributes])

    # A collection here would be a malformed upstream response, so it raises a typed transport
    # error rather than being asserted on — this is a system boundary, not an internal invariant.
    resource = single_resource(document, path=path)
    attributes = resource.attributes.model_dump(exclude_none=True) if resource is not None else {}
    # `confirm_name` isn't used here: the organization is fetched anyway, so the name comes
    # from that response rather than an extra request.
    resolved = party if party.name is not None else _with_name(party, attributes.get("name"))
    return OrganizationResolvedResponse(
        organization=attributes,
        resolved=party_echo(resolved),
        as_of=as_of_echo(extract_as_of(attributes)),
    )


def _with_name(party: ResolvedParty, name: object) -> ResolvedParty:
    cleaned = as_clean_str(name)
    if cleaned is None:
        return party
    return ResolvedParty(id=party.id, type=party.type, name=cleaned)
