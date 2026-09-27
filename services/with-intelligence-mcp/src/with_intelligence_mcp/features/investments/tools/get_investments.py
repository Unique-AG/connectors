from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from with_intelligence_mcp.features.investments import InvestorPositionsResponse
from with_intelligence_mcp.features.investments.dependencies import (
    get_investments_query_factory,
)
from with_intelligence_mcp.features.investments.queries import GetInvestmentsQuery
from with_intelligence_mcp.features.investors import (
    InvestorAmbiguousResponse,
    InvestorExtendedAttributes,
    InvestorNotFoundResponse,
)
from with_intelligence_mcp.features.investors.dependencies import (
    get_resolve_investor_record_query_factory,
)
from with_intelligence_mcp.features.investors.queries import ResolveInvestorRecordQuery
from with_intelligence_mcp.models import published_output_schema
from with_intelligence_mcp.with_intelligence_client import NotEntitled

type GetInvestmentsResult = (
    InvestorPositionsResponse | InvestorAmbiguousResponse | InvestorNotFoundResponse
)


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(GetInvestmentsResult),
)
async def get_investments(
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
    limit: Annotated[int, Field(ge=1, le=50, description="How many positions to return.")] = 25,
    updated_since: Annotated[
        str | None,
        Field(
            description=(
                "ISO date. Only positions With Intelligence changed since then — how to answer "
                "'what moved in the last 12 months'."
            )
        ),
    ] = None,
    resolve_investor_record_query: ResolveInvestorRecordQuery = Depends(
        get_resolve_investor_record_query_factory
    ),
    get_investments_query: GetInvestmentsQuery = Depends(get_investments_query_factory),
) -> GetInvestmentsResult:
    """An investor's fund roster: which funds they hold, through which manager, at what size,
    and which positions they have exited.

    Amounts are in MILLIONS of the stated currency. A position with an exit date is no longer
    held — do not present it as current. `fund_unidentified` means With Intelligence records the
    position but not which fund it is in, which is not the same as holding nothing.
    """
    investor = await resolve_investor_record_query.run(name=name, investor_id=investor_id)
    if not isinstance(investor, InvestorExtendedAttributes):
        return investor

    try:
        return await get_investments_query.run(
            investor=investor,
            limit=limit,
            updated_since=updated_since,
        )
    except NotEntitled as error:
        return InvestorNotFoundResponse(
            searched_for=name or str(investor.id),
            hint=f"With Intelligence refused {error.path} for this account.",
        )
