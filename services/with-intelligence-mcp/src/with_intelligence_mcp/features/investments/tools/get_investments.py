import asyncio
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from with_intelligence_mcp.features.investments import (
    InvestorPositionsResponse,
    PositionResponse,
    fetch_investment,
    fetch_investments_for_investor,
    project_position,
)
from with_intelligence_mcp.features.investors import (
    InvestorAmbiguousResponse,
    InvestorExtendedAttributes,
    InvestorNotFoundResponse,
    resolve_investor_record,
)
from with_intelligence_mcp.features.wi_session import get_with_intelligence_client
from with_intelligence_mcp.with_intelligence_client import NotEntitled, WithIntelligenceClient

type GetInvestmentsResult = (
    InvestorPositionsResponse | InvestorAmbiguousResponse | InvestorNotFoundResponse
)


@tool(annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True))
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
    client: WithIntelligenceClient = Depends(get_with_intelligence_client),
) -> GetInvestmentsResult:
    """An investor's fund roster: which funds they hold, through which manager, at what size,
    and which positions they have exited.

    Amounts are in MILLIONS of the stated currency. A position with an exit date is no longer
    held — do not present it as current. `fund_unidentified` means With Intelligence records the
    position but not which fund it is in, which is not the same as holding nothing.
    """
    investor = await resolve_investor_record(client, name, investor_id)
    if not isinstance(investor, InvestorExtendedAttributes):
        return investor
    resolved = investor.id

    try:
        listed, total = await fetch_investments_for_investor(
            client, resolved, limit=limit, updated_since=updated_since
        )
    except NotEntitled as error:
        return InvestorNotFoundResponse(
            searched_for=name or str(resolved),
            hint=f"With Intelligence refused {error.path} for this account.",
        )

    details = await asyncio.gather(*(fetch_investment(client, position.id) for position in listed))
    positions = [
        project_position(detail) if detail else PositionResponse(id=listed[index].id)
        for index, detail in enumerate(details)
    ]

    return InvestorPositionsResponse(
        investor_id=resolved,
        investor_name=investor.name,
        positions=positions,
        total=total,
        returned=len(positions),
    )
