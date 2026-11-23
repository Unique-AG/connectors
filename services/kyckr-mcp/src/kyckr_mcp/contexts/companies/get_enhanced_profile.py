from kyckr_mcp.upstream import GET_COMPANIES_KYCKR_ID_ENHANCED
from kyckr_mcp.upstream import GetCompaniesKyckrIdEnhancedPath
from kyckr_mcp.upstream import GetCompaniesKyckrIdEnhancedQuery
from kyckr_mcp.upstream import GetCompaniesKyckrIdEnhancedRequest
from kyckr_mcp.upstream import GetCompaniesKyckrIdEnhancedResponse
from kyckr_mcp.upstream import Upstream


async def get_enhanced_profile(
    *, upstream: Upstream, kyckr_id: str, customer_reference: str | None
) -> GetCompaniesKyckrIdEnhancedResponse:
    request = GetCompaniesKyckrIdEnhancedRequest(
        path=GetCompaniesKyckrIdEnhancedPath(kyckr_id=kyckr_id),
        query=GetCompaniesKyckrIdEnhancedQuery(
            customer_reference=customer_reference, show_directorships=None
        ),
    )
    return await upstream.call(GET_COMPANIES_KYCKR_ID_ENHANCED, request)
