from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from with_intelligence_mcp.features.investors import (
    InvestorAmbiguousResponse,
    InvestorNotEntitledResponse,
    InvestorNotFoundResponse,
    InvestorProfileResponse,
)
from with_intelligence_mcp.features.investors.dependencies import get_investor_query_factory
from with_intelligence_mcp.features.investors.queries import GetInvestorQuery
from with_intelligence_mcp.models import published_output_schema

type GetInvestorResult = (
    InvestorProfileResponse
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
    output_schema=published_output_schema(GetInvestorResult),
)
async def get_investor(
    name: Annotated[
        str | None,
        Field(
            description=(
                "Investor name, e.g. 'Virginia Retirement System'. Use the institution's "
                "registered name rather than an abbreviation. Omit when passing investor_id."
            )
        ),
    ] = None,
    investor_id: Annotated[
        int | None,
        Field(description="With Intelligence investor id, when it is already known."),
    ] = None,
    get_investor_query: GetInvestorQuery = Depends(get_investor_query_factory),
) -> GetInvestorResult:
    """Profile one institutional investor: type, AUM, location, the strategies and structures
    they allocate to, who they currently invest with, their consultants, and key contacts.

    Pass a name and it is resolved first; several matches come back as candidates to choose
    between. An absent field is unknown to With Intelligence rather than zero, and
    `preferences_available: false` means this subscription lacks the Intentions & Preferences
    add-on — not that the investor has stated no preferences.
    """
    return await get_investor_query.run(name=name, investor_id=investor_id)
