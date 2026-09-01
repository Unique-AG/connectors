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
from with_intelligence_mcp.features.persons import (
    PeopleForInvestorResponse,
    PersonResponse,
    fetch_people_for_organisation,
    fetch_person,
    project_person,
)
from with_intelligence_mcp.features.vendor_session import get_with_intelligence_client
from with_intelligence_mcp.with_intelligence_client import NotEntitled, WithIntelligenceClient

type GetPeopleResult = (
    PeopleForInvestorResponse | InvestorAmbiguousResponse | InvestorNotFoundResponse
)


@tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
async def get_people_for_investor(
    name: Annotated[
        str | None,
        Field(
            description=(
                "Investor name. Matching is partial, so 'Virginia' finds every investor whose "
                "name contains it. Omit when passing investor_id."
            )
        ),
    ] = None,
    investor_id: Annotated[int | None, Field(description="Investor id, when known.")] = None,
    limit: Annotated[
        int, Field(ge=1, le=50, description="How many people to return, most recent first.")
    ] = 25,
    client: WithIntelligenceClient = Depends(get_with_intelligence_client),
) -> GetPeopleResult:
    """Contacts at one institutional investor, with the role each holds there: job title,
    seniority, email and phone where recorded, and whether they have left.

    Seniority is the closest thing the data has to a decision-maker flag. A contact whose role
    carries an end date has left — say so rather than presenting them as reachable.

    The two counts this returns disagree: the person search and the investor record hold
    different numbers of contacts, and which is authoritative is undocumented.
    """
    resolved = await _resolve(client, name, investor_id)
    if not isinstance(resolved, int):
        return resolved

    try:
        listed, total = await fetch_people_for_organisation(client, resolved, limit=limit)
    except NotEntitled as error:
        return InvestorNotFoundResponse(
            searched_for=name or str(resolved),
            hint=f"With Intelligence refused {error.path} for this account.",
        )

    details = await asyncio.gather(
        *(fetch_person(client, person.id) for person in listed), return_exceptions=False
    )
    people = [
        project_person(detail, resolved)
        if detail
        else PersonResponse(id=listed[index].id, name=listed[index].name)
        for index, detail in enumerate(details)
    ]

    investor = await fetch_investor(client, resolved)
    return PeopleForInvestorResponse(
        investor_id=resolved,
        investor_name=investor.name if investor else name,
        people=people,
        total_at_organisation=total,
        returned=len(people),
    )


async def _resolve(
    client: WithIntelligenceClient, name: str | None, investor_id: int | None
) -> int | InvestorAmbiguousResponse | InvestorNotFoundResponse:
    if investor_id is not None:
        return investor_id
    if name is None:
        return InvestorNotFoundResponse(searched_for="", hint="Pass either name or investor_id.")
    return await resolve_investor(client, name)
