"""`get_opportunities`: a party's pipeline, with stage names and stage history.

Resolves the party the same way `get_activity_history` does (`search_type` plus a trusted
`party_id` or a `search`), then overlaps the party's
`/{segment}/{id}/opportunities?include=stage,stageHistory` walk with the TTL-cached stage
vocabulary. Filtering by `status` and ordering by `dateEnteredCurrentStage` happen in memory:
Backstop 400s `filter[isOpen]` and silently ignores `sort=` on this sub-collection.

There is no cursor. Paging outward would let a party whose open deals sit on page 3 receive an
authoritative-looking empty answer for `status="open"`. No party in the instance exceeds 50
opportunities, so the whole sub-collection is walked.
"""

import logging
from typing import Annotated, Literal

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.opportunities import (
    OpportunityFetchResponse,
    OpportunityResponse,
    OpportunityStagesService,
    OpportunityStatus,
    fetch_opportunities,
    get_opportunity_stages_service,
)
from backstop_mcp.features.party_resolver import (
    PartyAmbiguousResponse,
    ResolvedPartyResponse,
    resolve_party,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved
from backstop_mcp.models import OmitNoneModel, published_output_schema

logger = logging.getLogger(__name__)


class OpportunitiesResolvedResponse(OmitNoneModel):
    """`get_opportunities` once the party was found and its pipeline fetched.

    `total` / `open_count` / `closed_count` are over everything fetched — the party's complete
    set — so `status="open"` still reports how many closed deals exist. `previous_stage` on each
    deal names the stage it just left, and is omitted until it has moved at all.
    """

    status: Literal["resolved"] = Field(
        default="resolved",
        description="Always 'resolved': the party was found and its pipeline fetched.",
    )
    resolved: ResolvedPartyResponse = Field(
        description=(
            "The identity this call settled on. Echo `id` / `search_type` / `name` as "
            "`party_id` later — never invent them."
        )
    )
    opportunities: tuple[OpportunityResponse, ...] = Field(
        description=(
            "The deals matching the requested status, newest first by the day each entered "
            + "its current stage."
        )
    )
    total: int = Field(
        description=(
            "Every opportunity fetched for this party, before filtering by status — so the "
            + "number they have in total."
        )
    )
    open_count: int = Field(
        description=(
            "How many of those are open, whatever status was asked for — so an answer about "
            + "open deals still says how many exist."
        )
    )
    closed_count: int = Field(
        description="How many of those are closed, counted the same way as `open_count`."
    )


type GetOpportunitiesResponse = (
    PartyAmbiguousResponse | NotFoundResponse | OpportunitiesResolvedResponse
)


def _resolved_response(
    *, resolved: ResolvedPartyResponse, fetched: OpportunityFetchResponse
) -> OpportunitiesResolvedResponse:
    return OpportunitiesResolvedResponse(
        resolved=resolved,
        opportunities=fetched.opportunities,
        total=fetched.total,
        open_count=fetched.open_count,
        closed_count=fetched.closed_count,
    )


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    output_schema=published_output_schema(GetOpportunitiesResponse),
)
async def get_opportunities(
    ctx: Context,
    search_type: Annotated[
        SearchType,
        Field(
            description=(
                "Which Backstop collection to resolve the party against — fold the caller's "
                "wording to one of the four. A company, firm, fund, institution, or manager is "
                "`organizations`; any human is `people`. Pick `contacts` or `employees` only "
                "when a prior resolve echoed one (echo it back — a contact or employee id is "
                "not a people id) or the caller clearly means an internal staff member."
            ),
        ),
    ],
    party_id: Annotated[
        str | None,
        Field(
            description=(
                "Trusted Backstop Party ID from a prior resolve echo (`id` / `search_type` / "
                "`name`). Never invent or guess. Exactly one of `party_id` or `search` must be "
                "provided."
            ),
        ),
    ] = None,
    search: Annotated[
        str | None,
        Field(
            description=(
                "Name or email to resolve when no trusted `party_id` is available. Exactly one "
                "of `party_id` or `search` must be provided."
            ),
        ),
    ] = None,
    status: Annotated[
        OpportunityStatus,
        Field(
            description=(
                "Which deals to return: `open`, `closed`, or `all`. Defaults to `all`. "
                "`open_count` and `closed_count` on the response still report the split."
            ),
        ),
    ] = "all",
    client: BackstopClient = Depends(get_backstop_client),
    opportunity_stages: OpportunityStagesService = Depends(get_opportunity_stages_service),
) -> GetOpportunitiesResponse:
    """Fetch a party's opportunities: stage, stage timing, and how each deal got there.

    Pass `search_type` plus a trusted `party_id` (from a prior resolve echo — never invent or
    guess one) or `search`. When retrying with `party_id`, pass that resolve's `search_type`
    — a contact or employee id is not a people id.

    There is no cursor. The whole party's pipeline is returned, filtered by `status` (`open` /
    `closed` / `all`, default `all`) and ordered newest-first by the day each deal entered its
    current stage. `total`, `open_count` and `closed_count` are over that complete set, so an
    open-only answer still says how many closed deals exist.

    `stage` is where the deal is now. `previous_stage` is the stage it most recently LEFT, and
    is omitted until the deal has moved at all — do not read it as the current stage. Stage
    names are this instance's vocabulary, returned on each deal. `weighted_value` /
    `weighted_allocated_value` are Backstop's own products of amount and probability.
    `probability` is the standard attribute; a rep-entered probability custom field stays in
    `custom_field_values` under its own name. Master Pipeline fields are those custom-field
    entries — call `list_custom_fields` with entity_types opportunities for definitions.
    """
    result = await resolve_party(
        ctx,
        client,
        search_type=search_type,
        party_id=party_id,
        search=search,
    )
    if not isinstance(result, Resolved):
        return unresolved_party_response(result)

    party = result.value
    logger.info(
        "opportunities.get.start",
        extra={"segment": party.search_type, "entity_id": party.id, "status": status},
    )
    fetched = await fetch_opportunities(
        client,
        segment=party.search_type,
        entity_id=party.id,
        status=status,
        vocabulary=opportunity_stages.get(client),
    )
    logger.info(
        "opportunities.get.completed",
        extra={
            "segment": party.search_type,
            "entity_id": party.id,
            "status": status,
            "total": fetched.total,
            "returned": len(fetched.opportunities),
        },
    )
    return _resolved_response(resolved=ResolvedPartyResponse.from_party(party), fetched=fetched)
