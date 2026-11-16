from kyckr_mcp.upstream import GET_COMPANIES_KYCKR_ID_DOCUMENTS
from kyckr_mcp.upstream import GetCompaniesKyckrIdDocumentsPath
from kyckr_mcp.upstream import GetCompaniesKyckrIdDocumentsQuery
from kyckr_mcp.upstream import GetCompaniesKyckrIdDocumentsRequest
from kyckr_mcp.upstream import GetCompaniesKyckrIdDocumentsResponse
from kyckr_mcp.upstream import Upstream


async def list_company_documents(
    *,
    upstream: Upstream,
    kyckr_id: str,
    continuation_key: str | None,
    customer_reference: str | None,
) -> GetCompaniesKyckrIdDocumentsResponse:
    request = GetCompaniesKyckrIdDocumentsRequest(
        path=GetCompaniesKyckrIdDocumentsPath(kyckr_id=kyckr_id),
        query=GetCompaniesKyckrIdDocumentsQuery(
            continuation_key=continuation_key, customer_reference=customer_reference
        ),
    )
    return await upstream.call(GET_COMPANIES_KYCKR_ID_DOCUMENTS, request)
