"""`create_opportunity`: POST one deal. Investor is a party, never a raw id."""

import logging
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.opportunity_writes import (
    CREATE_OPPORTUNITY_INPUT_DESCRIPTION,
    CreateOpportunityCommand,
    CreateOpportunityInput,
    CreateOpportunityResponse,
    get_create_opportunity_command_factory,
)
from backstop_mcp.features.party_resolver import (
    ResolvePartyQuery,
    get_resolve_party_query_factory,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import Resolved, elicit_if_ambiguous
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)


@tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(CreateOpportunityResponse),
)
async def create_opportunity(
    ctx: Context,
    opportunity: Annotated[
        CreateOpportunityInput, Field(description=CREATE_OPPORTUNITY_INPUT_DESCRIPTION)
    ],
    resolve_party_query: ResolvePartyQuery = Depends(get_resolve_party_query_factory),
    create_opportunity_command: CreateOpportunityCommand = Depends(
        get_create_opportunity_command_factory
    ),
) -> CreateOpportunityResponse:
    """Create one CRM opportunity.

    `name`, `currency_code`, `is_erisa`, and the investor identity are required. Investor
    identity is the same as `get_person`: exactly one of `party_id` or `search`, plus
    `search_type` (defaults to contacts). The POST relationship is always a `contacts`
    pointer. `stage` is a **name** resolved against this instance's vocabulary, not an
    id. A repeated call creates a second record. Custom fields go through
    `update_custom_field_values`. To change an existing deal, use `update_opportunity`.
    `destructive_hint` is true because this writes a new CRM record.

    Call like: {"opportunity": {"name": "Koch - CATS Select", "currency_code": "USD",
    "is_erisa": false, "search_type": "contacts",
    "party_id": "<id from get_person with search_type contacts>", "stage": "Prospect"}}
    """
    investor_result = await resolve_party_query.run(
        search_type=opportunity.search_type,
        party_id=opportunity.party_id,
        search=opportunity.search,
    )
    investor_result = await elicit_if_ambiguous(ctx, investor_result)
    if not isinstance(investor_result, Resolved):
        return unresolved_party_response(investor_result)
    investor = investor_result.value
    logger.info(
        "opportunity_writes.create_opportunity.start",
        extra={"investor_id": investor.id, "investor_search_type": investor.search_type},
    )
    return await create_opportunity_command.run(opportunity=opportunity, investor_id=investor.id)
