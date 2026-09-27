from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from with_intelligence_mcp.features.investors import (
    InvestorAmbiguousResponse,
    InvestorExtendedAttributes,
    InvestorNotFoundResponse,
)
from with_intelligence_mcp.features.investors.dependencies import (
    get_resolve_investor_record_query_factory,
)
from with_intelligence_mcp.features.investors.queries import ResolveInvestorRecordQuery
from with_intelligence_mcp.features.persons import PeopleForInvestorResponse
from with_intelligence_mcp.features.persons.dependencies import (
    get_people_for_investor_query_factory,
)
from with_intelligence_mcp.features.persons.queries import GetPeopleForInvestorQuery
from with_intelligence_mcp.models import published_output_schema
from with_intelligence_mcp.with_intelligence_client import NotEntitled

type GetPeopleResult = (
    PeopleForInvestorResponse | InvestorAmbiguousResponse | InvestorNotFoundResponse
)


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(GetPeopleResult),
)
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
    resolve_investor_record_query: ResolveInvestorRecordQuery = Depends(
        get_resolve_investor_record_query_factory
    ),
    get_people_for_investor_query: GetPeopleForInvestorQuery = Depends(
        get_people_for_investor_query_factory
    ),
) -> GetPeopleResult:
    """Contacts at one institutional investor, with the role each holds there: job title,
    seniority, email and phone where recorded, and whether they have left.

    Seniority is the closest thing the data has to a decision-maker flag. A contact whose role
    carries an end date has left — say so rather than presenting them as reachable.

    The two counts this returns disagree: the person search and the investor record hold
    different numbers of contacts, and which is authoritative is undocumented.
    """
    investor = await resolve_investor_record_query.run(name=name, investor_id=investor_id)
    if not isinstance(investor, InvestorExtendedAttributes):
        return investor

    try:
        return await get_people_for_investor_query.run(investor=investor, limit=limit)
    except NotEntitled as error:
        return InvestorNotFoundResponse(
            searched_for=name or str(investor.id),
            hint=f"With Intelligence refused {error.path} for this account.",
        )
