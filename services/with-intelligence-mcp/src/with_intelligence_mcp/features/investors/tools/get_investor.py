from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from with_intelligence_mcp.features.investors import (
    InvestorAmbiguousResponse,
    InvestorNotFoundResponse,
    InvestorProfileResponse,
    fetch_investor,
    project_investor,
    resolve_investor,
)
from with_intelligence_mcp.features.vendor_session import get_with_intelligence_client
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient

type GetInvestorResult = (
    InvestorProfileResponse | InvestorAmbiguousResponse | InvestorNotFoundResponse
)


@tool(
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
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
    client: WithIntelligenceClient = Depends(get_with_intelligence_client),
) -> GetInvestorResult:
    """Profile one institutional investor: type, AUM, location, the strategies and structures
    they allocate to, who they currently invest with, their consultants, and key contacts.

    Pass a name and it is resolved first; several matches come back as candidates to choose
    between. An absent field is unknown to With Intelligence rather than zero, and
    `preferences_available: false` means this subscription lacks the Intentions & Preferences
    add-on — not that the investor has stated no preferences.
    """
    if investor_id is None and name is None:
        return InvestorNotFoundResponse(searched_for="", hint="Pass either name or investor_id.")

    if investor_id is None:
        assert name is not None
        resolved = await resolve_investor(client, name)
        if not isinstance(resolved, int):
            return resolved
        investor_id = resolved

    record = await fetch_investor(client, investor_id)
    if record is None:
        return InvestorNotFoundResponse(
            searched_for=name or str(investor_id),
            hint=f"No investor with id {investor_id}.",
        )
    return project_investor(record)
