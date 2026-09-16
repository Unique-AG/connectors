import asyncio
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from with_intelligence_mcp.features.investors import (
    InvestorAmbiguousResponse,
    InvestorExtendedAttributes,
    InvestorNotFoundResponse,
    resolve_investor_record,
)
from with_intelligence_mcp.features.mandates import (
    InvestorMandatesResponse,
    MandateResponse,
    fetch_mandate,
    fetch_mandates_for_investor,
    project_mandate,
)
from with_intelligence_mcp.features.wi_session import get_with_intelligence_client
from with_intelligence_mcp.with_intelligence_client import NotEntitled, WithIntelligenceClient

type GetMandatesResult = (
    InvestorMandatesResponse | InvestorAmbiguousResponse | InvestorNotFoundResponse
)


@tool(annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True))
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
    limit: Annotated[
        int, Field(ge=1, le=50, description="How many mandates to return, newest first.")
    ] = 25,
    updated_since: Annotated[
        str | None,
        Field(description="ISO date. Only mandates With Intelligence changed since then."),
    ] = None,
    client: WithIntelligenceClient = Depends(get_with_intelligence_client),
) -> GetMandatesResult:
    """An investor's allocation searches: what they are looking to allocate to, at what size,
    how far along each is, and which consultant is running it.

    `status` is With Intelligence's own vocabulary rather than a boolean — read it instead of
    assuming a mandate is live. `last_reviewed` is when they last confirmed it, so an old date
    means a stale mandate even where the status still reads open. Amounts are in MILLIONS.
    """
    investor = await resolve_investor_record(client, name, investor_id)
    if not isinstance(investor, InvestorExtendedAttributes):
        return investor
    resolved = investor.id

    try:
        listed, total = await fetch_mandates_for_investor(
            client, resolved, limit=limit, updated_since=updated_since
        )
    except NotEntitled as error:
        return InvestorNotFoundResponse(
            searched_for=name or str(resolved),
            hint=f"With Intelligence refused {error.path} for this account.",
        )

    details = await asyncio.gather(*(fetch_mandate(client, entry.id) for entry in listed))
    mandates = [
        project_mandate(detail) if detail else MandateResponse(id=listed[index].id)
        for index, detail in enumerate(details)
    ]

    return InvestorMandatesResponse(
        investor_id=resolved,
        investor_name=investor.name,
        mandates=mandates,
        total=total,
        returned=len(mandates),
    )
