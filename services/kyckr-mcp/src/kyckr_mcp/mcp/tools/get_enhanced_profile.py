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
        "Get Enhanced Company Profile",
        PAID_READ,
        icon="building",
        system_prompt=(
            "Use when the user needs ownership data: directors / representatives, ultimate "
            "beneficial owners, share capital, contact details, or the registry activity "
            "declaration. Otherwise `get_lite_profile` covers identification at a lower credit "
            "cost. Spends credits - confirm the user wants this depth before calling. A "
            "`statusCode: 405` means the enhanced profile is not available synchronously for that "
            "jurisdiction; surface that limitation to the user rather than substituting another "
            "tool."
        ),
    )
)
@answers_failures
async def get_enhanced_profile(
    kyckr_id: KyckrId,
    upstream: Upstream = Depends(get_upstream),
    settings: UpstreamSettings = Depends(get_upstream_settings),
) -> Reply:
    """Fetch a paid Enhanced company profile using a confirmed `kyckr_id`. Returns everything in
    `get_lite_profile` plus representatives, ultimate beneficial owners, share capital, contact
    details, and activity declarations. Use only when ownership or representative data is
    needed; `get_lite_profile` is cheaper for basic identification. A `statusCode: 405`
    response means the enhanced profile is not available for that jurisdiction; tell the user
    and do not substitute `create_document_order`, which orders registry filings, not profile
    data. When `data.status` is `Pending` the profile is not ready yet: poll `get_order` with
    `data.orderId` until it resolves.
    """
    result = await contexts.get_enhanced_profile(
        upstream=upstream,
        kyckr_id=kyckr_id,
        customer_reference=settings.default_customer_reference,
    )
    return answer(Reply, result)
