import asyncio
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from with_intelligence_mcp.features.investors import (
    InvestorAmbiguousResponse,
    InvestorNotFoundResponse,
    fetch_investor,
    resolve_investor,
)
from with_intelligence_mcp.features.mandates import (
    InvestorMandatesResponse,
    MandateResponse,
    fetch_mandate,
    fetch_mandates_for_investor,
    project_mandate,
)
from with_intelligence_mcp.features.vendor_session import get_with_intelligence_client
from with_intelligence_mcp.with_intelligence_client import NotEntitled, WithIntelligenceClient

type GetMandatesResult = (
    InvestorMandatesResponse | InvestorAmbiguousResponse | InvestorNotFoundResponse
)


@tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
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
        Field(description="ISO date. Only mandates the vendor changed since then."),
    ] = None,
    client: WithIntelligenceClient = Depends(get_with_intelligence_client),
) -> GetMandatesResult:
    """An investor's allocation searches: what they are looking to allocate to, at what size,
    how far along each is, and which consultant is running it.

    `status` is the vendor's own vocabulary rather than a boolean — read it instead of assuming
    a mandate is live. `last_reviewed` is when they last confirmed it, so an old date means a
    stale mandate even where the status still reads open. Amounts are in MILLIONS.
    """
    resolved = await _resolve(client, name, investor_id)
    if not isinstance(resolved, int):
        return resolved

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

    investor = await fetch_investor(client, resolved)
    return InvestorMandatesResponse(
        investor_id=resolved,
        investor_name=investor.name if investor else name,
        mandates=mandates,
        total=total,
        returned=len(mandates),
    )


async def _resolve(
    client: WithIntelligenceClient, name: str | None, investor_id: int | None
) -> int | InvestorAmbiguousResponse | InvestorNotFoundResponse:
    if investor_id is not None:
        return investor_id
    if name is None:
        return InvestorNotFoundResponse(searched_for="", hint="Pass either name or investor_id.")
    return await resolve_investor(client, name)
