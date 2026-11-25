from pydantic import Field

from kyckr_mcp.contexts.replies import Cost
from kyckr_mcp.contexts.replies import KyckrModel
from kyckr_mcp.contexts.replies import Reply
from kyckr_mcp.upstream import GET_COMPANIES_KYCKR_ID_DOCUMENTS
from kyckr_mcp.upstream import GetCompaniesKyckrIdDocumentsPath
from kyckr_mcp.upstream import GetCompaniesKyckrIdDocumentsQuery
from kyckr_mcp.upstream import GetCompaniesKyckrIdDocumentsRequest
from kyckr_mcp.upstream import Upstream


async def list_company_documents(
    *,
    upstream: Upstream,
    kyckr_id: str,
    continuation_key: str | None,
    customer_reference: str | None,
) -> CompanyDocumentsReply:
    request = GetCompaniesKyckrIdDocumentsRequest(
        path=GetCompaniesKyckrIdDocumentsPath(kyckr_id=kyckr_id),
        query=GetCompaniesKyckrIdDocumentsQuery(
            continuation_key=continuation_key, customer_reference=customer_reference
        ),
    )
    response = await upstream.call(GET_COMPANIES_KYCKR_ID_DOCUMENTS, request)
    return CompanyDocumentsReply.model_validate(response)


class CompanyDocument(KyckrModel):
    """A registry document that can be ordered."""

    id: str | None = Field(None, description="The product id, passed as `product_id` to order.")
    name: str | None = Field(None, description="The name of the document.")
    category: str | None = Field(None, description="The kind of document.")
    document_date: str | None = Field(None, description="Its date, usually when it was filed.")
    delivery_time_minutes: int | None = Field(
        None, description="How long Kyckr expects delivery to take, in minutes."
    )
    document_format: list[str] | None = Field(
        None, description="The MIME types of the files an order of it returns."
    )
    cost: Cost | None = Field(None, description="What ordering it costs.")


class CompanyDocumentsReply(Reply):
    """A page of the documents a company has to order."""

    data: list[CompanyDocument] | None = Field(None, description="The documents.")
    continuation_key: str | None = Field(
        None,
        description=(
            "Pass it back as `continuation_key` to fetch the next page. Absent on the last page."
        ),
    )
