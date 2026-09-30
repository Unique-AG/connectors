from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from with_intelligence_mcp.features.investors import (
    InvestorAmbiguousResponse,
    InvestorExtendedAttributes,
    InvestorNotEntitledResponse,
    InvestorNotFoundResponse,
)
from with_intelligence_mcp.features.investors.dependencies import (
    get_resolve_investor_record_query_factory,
)
from with_intelligence_mcp.features.investors.queries import ResolveInvestorRecordQuery
from with_intelligence_mcp.features.mandates import InvestorMandatesResponse
from with_intelligence_mcp.features.mandates.dependencies import get_mandates_query_factory
from with_intelligence_mcp.features.mandates.queries import GetMandatesQuery
from with_intelligence_mcp.models import published_output_schema
from with_intelligence_mcp.with_intelligence_client import NotEntitled

type GetMandatesResult = (
    InvestorMandatesResponse
    | InvestorAmbiguousResponse
    | InvestorNotEntitledResponse
    | InvestorNotFoundResponse
)


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(GetMandatesResult),
)
async def get_mandates(
    name: Annotated[
        str | None,
        Field(
            description=(
                "Investor name. Matching is partial, so a short name returns candidates to "
                "choose between. Omit when passing investor_id."
            )
        ),
    ] = None,
    investor_id: Annotated[int | None, Field(description="Investor id, when known.")] = None,
    page: Annotated[int, Field(ge=1, description="Page number to return.")] = 1,
    limit: Annotated[
        int, Field(ge=1, le=50, description="How many mandates to return, newest first.")
    ] = 25,
    updated_since: Annotated[
        str | None,
        Field(description="ISO date. Only mandates With Intelligence changed since then."),
    ] = None,
    resolve_investor_record_query: ResolveInvestorRecordQuery = Depends(
        get_resolve_investor_record_query_factory
    ),
    get_mandates_query: GetMandatesQuery = Depends(get_mandates_query_factory),
) -> GetMandatesResult:
    """An investor's allocation searches: what they are looking to allocate to, at what size,
    how far along each is, and which consultant is running it.

    `status` is With Intelligence's own vocabulary rather than a boolean — read it instead of
    assuming a mandate is live. `last_reviewed` is when they last confirmed it, so an old date
    means a stale mandate even where the status still reads open. Amounts are in MILLIONS.
    """
    investor = await resolve_investor_record_query.run(name=name, investor_id=investor_id)
    if not isinstance(investor, InvestorExtendedAttributes):
        return investor

    try:
        return await get_mandates_query.run(
            investor=investor,
            page=page,
            limit=limit,
            updated_since=updated_since,
        )
    except NotEntitled as error:
        return InvestorNotEntitledResponse(
            searched_for=name or str(investor.id),
            hint=f"With Intelligence refused {error.path} for this account.",
        )
