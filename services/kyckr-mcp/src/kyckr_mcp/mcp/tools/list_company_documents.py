from fastmcp.dependencies import Depends
from fastmcp.tools import tool

from kyckr_mcp import contexts
from kyckr_mcp.mcp.dependencies import get_upstream
from kyckr_mcp.mcp.dependencies import get_upstream_settings
from kyckr_mcp.mcp.hints import FREE_READ
from kyckr_mcp.mcp.hints import tool_options
from kyckr_mcp.mcp.inputs.company import ContinuationKey
from kyckr_mcp.mcp.inputs.company import KyckrId
from kyckr_mcp.mcp.responses.failures import answers_failures
from kyckr_mcp.mcp.responses.replies import answer
from kyckr_mcp.mcp.responses.replies import CompanyDocumentsReply
from kyckr_mcp.upstream import Upstream
from kyckr_mcp.upstream import UpstreamSettings


@tool(
    **tool_options(
        "List Company Documents",
        FREE_READ,
        icon="file-text",
        system_prompt=(
            "Use to find filings the user can pay to retrieve as official artifacts (annual "
            "accounts, articles, mortgages, etc.). Free to call; always run this before "
            "`create_document_order` so you can show the user the document `name` and `cost.value` "
            "and obtain explicit confirmation."
        ),
    )
)
@answers_failures
async def list_company_documents(
    kyckr_id: KyckrId,
    continuation_key: ContinuationKey = None,
    *,
    upstream: Upstream = Depends(get_upstream),
    settings: UpstreamSettings = Depends(get_upstream_settings),
) -> CompanyDocumentsReply:
    """List official registry documents available to order for a company. The listing is free;
    only `create_document_order` consumes credits. Each entry includes a product `id` (use as
    `product_id` when ordering), `name`, `category`, `documentDate`, expected
    `deliveryTimeMinutes`, and the credit `cost` of ordering. Paginate with `continuation_key`
    when the response includes one.
    """
    result = await contexts.list_company_documents(
        upstream=upstream,
        kyckr_id=kyckr_id,
        continuation_key=continuation_key,
        customer_reference=settings.default_customer_reference,
    )
    return answer(CompanyDocumentsReply, result)
