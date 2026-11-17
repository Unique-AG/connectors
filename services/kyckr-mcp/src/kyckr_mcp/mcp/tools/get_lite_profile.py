from fastmcp.dependencies import Depends
from fastmcp.tools import tool

from kyckr_mcp import contexts
from kyckr_mcp.mcp.dependencies import get_upstream
from kyckr_mcp.mcp.dependencies import get_upstream_settings
from kyckr_mcp.mcp.hints import PAID_READ
from kyckr_mcp.mcp.hints import tool_options
from kyckr_mcp.mcp.inputs.company import KyckrId
from kyckr_mcp.mcp.responses.failures import answers_failures
from kyckr_mcp.mcp.responses.replies import answer
from kyckr_mcp.mcp.responses.replies import Reply
from kyckr_mcp.upstream import Upstream
from kyckr_mcp.upstream import UpstreamSettings


@tool(
    **tool_options(
        "Get Lite Company Profile",
        PAID_READ,
        icon="building",
        system_prompt=(
            "Use after `search_companies` when the user needs verified company identification "
            "(name, number, address, dates, legal form, status). Spends credits - confirm intent "
            "if there's any ambiguity, and prefer caching the result over re-fetching. If the user "
            "asks about directors / shareholders / UBOs, use `get_enhanced_profile` instead."
        ),
    )
)
@answers_failures
async def get_lite_profile(
    kyckr_id: KyckrId,
    upstream: Upstream = Depends(get_upstream),
    settings: UpstreamSettings = Depends(get_upstream_settings),
) -> Reply:
    """Fetch a paid Lite company profile using a confirmed `kyckr_id`. Returns basic verified
    registry details: company name, registration number, registered address, registration and
    foundation dates, legal form, legal status, activities, and registration authority.
    Consumes credits. Does not return directors, shareholders, or beneficial owners; use
    `get_enhanced_profile` for those. For orderable filings, see `list_company_documents`.
    """
    result = await contexts.get_lite_profile(
        upstream=upstream,
        kyckr_id=kyckr_id,
        customer_reference=settings.default_customer_reference,
    )
    return answer(Reply, result)
