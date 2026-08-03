from typing import ClassVar, Literal
from urllib.parse import quote

from fastmcp import Context
from pydantic import BaseModel, ConfigDict

from backstop_mcp.backstop_client import get_backstop_client
from backstop_mcp.backstop_client.json_api import BackstopApiDocument
from backstop_mcp.party_resolver import (
    NeedsDisambiguationResponse,
    NotFoundResponse,
    Resolved,
    ResolvedPartyEcho,
    early_exit_response,
    resolve_party,
)


class OrganizationAttributes(BaseModel):
    """Shape of an organization resource's `attributes` in `get_organization`'s response.

    `extra="allow"` so unrecognized Backstop fields (e.g. `status`) survive the
    `model_dump(exclude_none=True)` round-trip that rebuilds the `organization` dict.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow")

    name: str | None = None


class OrganizationResolvedResponse(BaseModel):
    """`get_organization`'s response once the organization was found and fetched."""

    status: Literal["resolved"] = "resolved"
    organization: dict[str, object]
    resolved: ResolvedPartyEcho


type GetOrganizationResponse = (
    NeedsDisambiguationResponse | NotFoundResponse | OrganizationResolvedResponse
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
    """
    async with await get_backstop_client() as client:
        result = await resolve_party(
            ctx,
            client,
            search_type="organizations",
            party_id=party_id,
            search=search,
        )

        if not isinstance(result, Resolved):
            return early_exit_response(result)

        party = result.party
        document = await client.get(
            f"/organizations/{quote(party.id, safe='')}",
            schema=BackstopApiDocument[OrganizationAttributes],
        )

    name = party.name
    if name is None and document.data is not None:
        if isinstance(document.data, list):
            raise ValueError(
                f"Backstop returned a collection for organization {party.id!r}; "
                + "expected a single resource"
            )
        name = document.data.attributes.name

    return OrganizationResolvedResponse(
        organization=document.model_dump(exclude_none=True),
        resolved=ResolvedPartyEcho(id=party.id, type=party.type, name=name),
    )
