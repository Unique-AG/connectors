from fastmcp.dependencies import Depends
from fastmcp.tools import tool

from kyckr_mcp import contexts
from kyckr_mcp.mcp.dependencies import get_upstream
from kyckr_mcp.mcp.dependencies import get_upstream_settings
from kyckr_mcp.mcp.hints import PAID_ORDER
from kyckr_mcp.mcp.hints import tool_options
from kyckr_mcp.mcp.inputs.company import KyckrId
from kyckr_mcp.mcp.inputs.order import ProductId
from kyckr_mcp.mcp.responses.failures import answers_failures
from kyckr_mcp.mcp.responses.replies import answer
from kyckr_mcp.mcp.responses.replies import Reply
from kyckr_mcp.upstream import Upstream
from kyckr_mcp.upstream import UpstreamSettings


@tool(
    **tool_options(
        "Order Document",
        PAID_ORDER,
        icon="file-text",
        system_prompt=(
            "Use only after the user has explicitly approved both the document and the credit cost "
            "shown by `list_company_documents`. The only tool that spends credits *and* creates "
            "state on Kyckr - never call speculatively, never retry on transient failure without a "
            "fresh confirmation. After a successful call, poll `get_order(data.orderId)` until it "
            "resolves."
        ),
    )
)
@answers_failures
async def create_document_order(
    kyckr_id: KyckrId,
    product_id: ProductId,
    *,
    upstream: Upstream = Depends(get_upstream),
    settings: UpstreamSettings = Depends(get_upstream_settings),
) -> Reply:
    """Place a paid Kyckr order for an official registry document. Every successful call
    spends credits and creates a real registry order; it is the only write-side tool.
    Required: `kyckr_id` (from `search_companies`) and `product_id` (from
    `list_company_documents`). Call directly once the user has named or chosen a
    specific filing; do not ask for a separate confirmation, the cost is already known.
    Returns `data.orderId` and `data.status`. On `status: "Success"` the JSON view of
    the document is inlined under `data.documentJson`; render it to the user as a
    readable summary. If `data.documentJson` is absent, `details` says the document is
    PDF-only and PDF delivery is not yet supported; relay that message. On `status:
    "Pending"`, poll `get_order(data.orderId)` until `data.documentJson` is populated or
    `status` is `Failed`. Never mention download URLs.
    """
    result = await contexts.create_document_order(
        upstream=upstream,
        kyckr_id=kyckr_id,
        product_id=product_id,
        customer_reference=settings.default_customer_reference,
        contact_email=settings.default_contact_email,
    )
    return answer(Reply, result)
