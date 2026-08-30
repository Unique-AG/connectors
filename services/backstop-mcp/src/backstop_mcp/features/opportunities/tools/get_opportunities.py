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
from collections.abc import Sequence
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.custom_fields import CustomFieldFilters
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.opportunities import (
    GetOpportunitiesQuery,
    OpportunitiesResolvedResponse,
    OpportunityStatus,
)
from backstop_mcp.features.opportunities.dependencies import get_opportunities_query_factory
from backstop_mcp.features.party_resolver import (
    PartyAmbiguousResponse,
    ResolvedPartyResponse,
    resolve_party,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved
from backstop_mcp.models import CoercedId, coerce_ids, published_output_schema

logger = logging.getLogger(__name__)

type GetOpportunitiesResponse = (
    PartyAmbiguousResponse | NotFoundResponse | OpportunitiesResolvedResponse
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
    custom_field_definition_ids: Annotated[
        Sequence[CoercedId],
        Field(
            description=(
                "Custom-field definition ids whose values to keep, as published on "
                "list_custom_fields `id` and on `custom_field_values[].definition_id`. "
                "JSON numbers are accepted. Combined with custom_field_names with AND. "
                "Omit to keep every definition."
            ),
        ),
    ] = (),
    custom_field_names: Annotated[
        Sequence[str],
        Field(
            description=(
                "Custom-field names whose values to keep. Case-insensitive. Combined with "
                "custom_field_definition_ids with AND. Omit to keep every name."
            ),
        ),
    ] = (),
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    get_opportunities_query: GetOpportunitiesQuery = Depends(get_opportunities_query_factory),
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
    entries, joined to list_custom_fields (field_type included). Slice with
    `custom_field_names` / `custom_field_definition_ids` — filters AND together. When
    `custom_fields_unavailable` is true, an empty list means the catalog could not be loaded,
    not that the deal has no Master Pipeline data.
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
    fetched = await get_opportunities_query.run(
        segment=party.search_type,
        entity_id=party.id,
        status=status,
        custom_fields_filters=CustomFieldFilters(
            definition_ids=coerce_ids(custom_field_definition_ids),
            names=tuple(custom_field_names),
        ),
    )
    return OpportunitiesResolvedResponse(
        resolved=ResolvedPartyResponse.from_party(party),
        opportunities=fetched.opportunities,
        total=fetched.total,
        open_count=fetched.open_count,
        closed_count=fetched.closed_count,
        custom_fields_unavailable=fetched.custom_fields_unavailable,
    )
