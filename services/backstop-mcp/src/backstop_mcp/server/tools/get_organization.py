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
    ProvenanceFields,
    as_of_response,
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
from backstop_mcp.server.runtime import get_backstop_client
from backstop_mcp.server.tools.results import tool_result


class OrganizationAttributes(ProvenanceFields):
    """Shape of an organization resource's `attributes` in `get_organization`'s response.

    `extra="allow"` so unrecognized Backstop fields survive on the typed payload, and so
    `extract_as_of` can read provenance from the model rather than string keys on a dump.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow", populate_by_name=True)

    name: str | None = None


class OrganizationResolvedResponse(BaseModel):
    """`get_organization`'s response once the organization was found and fetched.

    `organization` holds the record's own fields (the JSON:API resource's `attributes`) — not
    the enclosing document, whose `type`/`id` are already echoed under `resolved`.
    `as_of` is plain provenance (`modifiedTimestamp` / `modifiedBy`); relay it, do not treat
    age as a staleness verdict.
    """

    status: Literal["resolved"] = "resolved"
    organization: OrganizationAttributes
    resolved: ResolvedPartyResponse
    as_of: AsOf | None = None


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
    meta=glossary_meta(EntityType.ORGANIZATIONS),
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
) -> CallToolResult:
    """Fetch one Backstop organization by trusted Party ID or by name/email search.

    Never invent or guess a party_id. Only pass a party_id that was previously returned
    by this server's resolve echo (`id` / `search_type` / `name`). Otherwise pass `search`
    (organization name or email) and let the server resolve it.
    Exactly one of party_id or search must be provided.

    Responses include `as_of` provenance when Backstop provides modifiedTimestamp/modifiedBy.
    Relay that provenance to the user; do not treat record age as a staleness verdict.

    When the custom-field glossary on this tool is truncated or missing, call
    `list_custom_fields` with entity_type=organizations.
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
        return tool_result(unresolved_party_response(result))

    party = result.value
    path = f"/organizations/{quote(party.id, safe='')}"
    document = await client.get(path, schema=BackstopApiResourceDocument[OrganizationAttributes])
    attributes = document.data.attributes
    return tool_result(
        OrganizationResolvedResponse(
            organization=attributes,
            resolved=party_response(
                party, attributes=attributes.model_dump(by_alias=True, exclude_none=True)
            ),
            as_of=as_of_response(extract_as_of(attributes)),
        )
    )
