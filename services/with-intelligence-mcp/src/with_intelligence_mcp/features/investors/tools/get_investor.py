from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from with_intelligence_mcp.features.investors import (
    InvestorAmbiguousResponse,
    InvestorExtendedAttributes,
    InvestorNotFoundResponse,
    InvestorProfileResponse,
    project_investor,
    resolve_investor_record,
)
from with_intelligence_mcp.features.wi_session import get_with_intelligence_client
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient

type GetInvestorResult = (
    InvestorProfileResponse | InvestorAmbiguousResponse | InvestorNotFoundResponse
)


@tool(
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True),
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
    record = await resolve_investor_record(client, name, investor_id)
    if not isinstance(record, InvestorExtendedAttributes):
        return record
    return project_investor(record)
