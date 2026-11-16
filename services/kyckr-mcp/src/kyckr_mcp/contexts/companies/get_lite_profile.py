from kyckr_mcp.upstream import GET_COMPANIES_KYCKR_ID
from kyckr_mcp.upstream import GetCompaniesKyckrIdPath
from kyckr_mcp.upstream import GetCompaniesKyckrIdQuery
from kyckr_mcp.upstream import GetCompaniesKyckrIdRequest
from kyckr_mcp.upstream import GetCompaniesKyckrIdResponse
from kyckr_mcp.upstream import Upstream


async def get_lite_profile(
    *, upstream: Upstream, kyckr_id: str, customer_reference: str | None
) -> GetCompaniesKyckrIdResponse:
    request = GetCompaniesKyckrIdRequest(
        path=GetCompaniesKyckrIdPath(kyckr_id=kyckr_id),
        query=GetCompaniesKyckrIdQuery(customer_reference=customer_reference),
    )
    return await upstream.call(GET_COMPANIES_KYCKR_ID, request)
