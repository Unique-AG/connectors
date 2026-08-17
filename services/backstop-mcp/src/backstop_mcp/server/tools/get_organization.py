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
    ProvenanceFields,
    as_of_response,
    extract_as_of,
)
from backstop_mcp.features.includes import (
    OrganizationInclude,
    OrganizationIncludesResponse,
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
from backstop_mcp.server.runtime import get_backstop_client


class OrganizationAttributes(OmitNoneModel, ProvenanceFields):
    """Shape of an organization resource's `attributes` in `get_organization`'s response.

    `extra="allow"` so unrecognized Backstop fields survive on the typed payload, and so
    `extract_as_of` can read provenance from the model rather than string keys on a dump.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="allow", populate_by_name=True)

    name: str | None = None


class OrganizationResolvedResponse(OmitNoneModel):
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
    included: OrganizationIncludesResponse | None = Field(
        default=None,
        description=(
            "The related records asked for through `include`, side-loaded on the same request. "
            "Absent when no include was asked for."
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
) -> GetOrganizationResponse:
    """Fetch one Backstop organization by trusted Party ID or by name/email search.

    Never invent or guess a party_id. Only pass a party_id that was previously returned
    by this server's resolve echo (`id` / `search_type` / `name`). Otherwise pass `search`
    (organization name or email) and let the server resolve it.
    Exactly one of party_id or search must be provided.

    Pass `include` to side-load related records on the same request — addresses, the email
    address book, the primary contact, the representative. They come back under `included`,
    where a requested list is `[]` when there is nothing on file; omit `include` and only the
    organization's own fields are returned. `representative` is the colleague at our own firm
    who owns the relationship, not a way to contact the organization.

    Responses include `as_of` provenance when Backstop provides modifiedTimestamp/modifiedBy.
    Relay that provenance to the user; do not treat record age as a staleness verdict.

    When you need custom field names for this organization, call `list_custom_fields` with
    entity_types including organizations.
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
    plan = include_plan(OrganizationIncludesResponse, requested=include)
    document = await client.get(
        path,
        params={"include": plan.param} if plan.param else None,
        schema=BackstopApiResourceDocument[OrganizationAttributes],
    )
    attributes = document.data.attributes
    return OrganizationResolvedResponse(
        organization=attributes,
        resolved=party_response(
            party, attributes=attributes.model_dump(by_alias=True, exclude_none=True)
        ),
        as_of=as_of_response(extract_as_of(attributes)),
        included=plan.project(document=document) if plan.planned else None,
    )
