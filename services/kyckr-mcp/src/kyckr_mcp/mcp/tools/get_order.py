from fastmcp.dependencies import Depends
from fastmcp.tools import tool

from kyckr_mcp import contexts
from kyckr_mcp.mcp.dependencies import get_upstream
from kyckr_mcp.mcp.hints import FREE_READ
from kyckr_mcp.mcp.hints import tool_options
from kyckr_mcp.mcp.inputs.order import OrderId
from kyckr_mcp.mcp.responses.failures import answers_failures
from kyckr_mcp.upstream import Upstream


@tool(
    **tool_options(
        "Get Order",
        FREE_READ,
        icon="file-text",
        system_prompt=(
            "Use to poll a `Pending` order until it resolves to `Success` (the document is then "
            "included) or `Failed`. Also useful for re-fetching the document of a previously "
            "completed order. Treat an error that starts `Kyckr answered 410` as terminal - the "
            "document is gone, do not retry."
        ),
    )
)
@answers_failures
async def get_order(
    order_id: OrderId, upstream: Upstream = Depends(get_upstream)
) -> contexts.OrderReply:
    """Retrieve a single Kyckr order by `order_id`. Free to call. Use to poll an order placed via
    `create_document_order` until `data.status` is `Success` or `Failed`. On `Success` the JSON
    view of the document is inlined under `data.documentJson`; render it to the user as a
    readable summary. If it is absent, `details` says the document is PDF-only and PDF
    delivery is not yet supported; relay that message. Treat an error that starts
    `Kyckr answered 410` as terminal: the order is no longer retrievable, do not retry. Never
    mention download URLs.
    """
    return await contexts.get_order(upstream=upstream, order_id=str(order_id))
