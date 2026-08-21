"""`get_people_for_party`: people linked to an organization, with employment status there.

`numberOfEmployees` on the organization record is not a roster. Current staff come from
`GET /organizations/{id}/employees` with a sparse employee fieldset and
`include=entityRelationships,entityRelationships.entityRelationshipType`.
Status is `EmploymentIndex` over those side-loads and the organization's
`entityRelationships`. Former people are not on `/employees`; when `include_former` is
false they are counted on `former_omitted` rather than listed.
"""

import logging
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client
from backstop_mcp.features.data_hygiene import (
    EmploymentIndexFactory,
    get_employment_index_factory,
)
from backstop_mcp.features.org_people import (
    OrgPeopleResolvedResponse,
    fetch_people_for_organization,
)
from backstop_mcp.features.party_resolver import (
    PartyAmbiguousResponse,
    ResolvedPartyResponse,
    resolve_party,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)

type GetPeopleForPartyResponse = (
    PartyAmbiguousResponse | NotFoundResponse | OrgPeopleResolvedResponse
)


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    output_schema=published_output_schema(GetPeopleForPartyResponse),
)
async def get_people_for_party(
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
    include_former: Annotated[
        bool,
        Field(
            description=(
                "When false (default), only current employment at this organization is "
                "returned. Pass true to include former employees. Do not present a former "
                "row as a live contact unless they asked for historical contacts."
            ),
        ),
    ] = False,
    client: BackstopClient = Depends(get_backstop_client),
    employment_index_factory: EmploymentIndexFactory = Depends(get_employment_index_factory),
) -> GetPeopleForPartyResponse:
    """List the people Backstop links to an organization, with employment status at that org.

    Pass a trusted `party_id` (from a prior resolve echo — never invent one) or `search`.
    This is the roster of current staff: `numberOfEmployees` on `get_organization` is often 0
    even when people are on file. Name and email come from `/employees` (same ids as people)
    side-loaded with employment relationships on that walk — not a fetch per person.

    Each row is identity (`id` / `search_type` / name / email / `categories`) plus
    `employment` from `EmploymentIndex` — `status` is `current` or `former` at this
    organization. Default is current only. `/employees` does not list former staff; those
    links are on the organization's `entityRelationships`. When they are omitted,
    `former_omitted` and `include_former_hint` say so — pass `include_former=true` to
    include them (contact fields may be absent). Call `get_person` with that row's `id`
    and `search_type` for the full record.
    """
    if (party_id is None) == (search is None):
        raise ValueError("Exactly one of party_id or search must be provided")

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
    logger.info(
        "org_people.start",
        extra={"entity_id": party.id, "include_former": include_former},
    )
    listing = await fetch_people_for_organization(
        client,
        employment_index_factory,
        organization_id=party.id,
        include_former=include_former,
    )
    logger.info(
        "org_people.completed",
        extra={
            "entity_id": party.id,
            "returned": len(listing.people),
            "former_omitted": listing.former_omitted,
            "people_omitted": listing.people_omitted,
        },
    )
    return OrgPeopleResolvedResponse.from_listing(
        listing, resolved=ResolvedPartyResponse.from_party(party)
    )
