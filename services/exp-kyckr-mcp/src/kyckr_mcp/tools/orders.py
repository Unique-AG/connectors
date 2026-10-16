from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_openapi.upstream import OperationClient

from kyckr_mcp.deps import get_api, get_settings
from kyckr_mcp.failures import answers_failures
from kyckr_mcp.hints import FREE_READ, PAID_ORDER, tool_options
from kyckr_mcp.models import operations
from kyckr_mcp.models.replies import ListOrdersReply, OrderReply
from kyckr_mcp.orders import as_order, created_order, finished_id, order_reply
from kyckr_mcp.params import EndDate, IsoCode, KyckrId, OrderId, ProductId, StartDate
from kyckr_mcp.settings import Settings


@tool(
    **tool_options(
        "Order Document",
        PAID_ORDER,
        "file-text",
        "Use only after the user has explicitly approved both the document and the credit cost "
        "shown by `list_company_documents`. The only tool that spends credits *and* creates "
        "state on Kyckr - never call speculatively, never retry on transient failure without a "
        "fresh confirmation. After a successful call, poll `get_order(data.orderId)` until it "
        "resolves.",
    )
)
@answers_failures
async def create_document_order(
    kyckr_id: KyckrId,
    product_id: ProductId,
    api: OperationClient = Depends(get_api),
    settings: Settings = Depends(get_settings),
) -> OrderReply:
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
    response = await api.call(
        operations.POST_ORDERS,
        kyckrId=kyckr_id,
        productId=product_id,
        customerReference=settings.kyckr_default_customer_reference,
        contactEmail=settings.kyckr_default_contact_email,
    )
    order = created_order(response)
    return await order_reply(api, response, order, finished_id(order))


@tool(
    **tool_options(
        "Get Order",
        FREE_READ,
        "file-text",
        "Use to poll a `Pending` order until it resolves to `Success` (the document is then "
        "included) or `Failed`. Also useful for re-fetching the document of a previously "
        "completed order. Treat `statusCode: 410` as terminal - the document is gone, do not "
        "retry.",
    )
)
@answers_failures
async def get_order(order_id: OrderId, api: OperationClient = Depends(get_api)) -> OrderReply:
    """Retrieve a single Kyckr order by `order_id`. Free to call. Use to poll an order placed via
    `create_document_order` until `data.status` is `Success` or `Failed`. On `Success` the JSON
    view of the document is inlined under `data.documentJson`; render it to the user as a
    readable summary. If it is absent, `details` says the document is PDF-only and PDF
    delivery is not yet supported; relay that message. Treat `statusCode: 410` as terminal:
    the order is no longer retrievable, do not retry. Never mention download URLs.
    """
    response = await api.call(operations.GET_ORDERS_ORDER_ID, orderId=str(order_id))
    order = as_order(response.data)
    return await order_reply(api, response, order, finished_id(order, str(order_id)))


@tool(
    **tool_options(
        "List Orders",
        FREE_READ,
        "file-text",
        "Use to find a prior order when the user references one by company or date but no "
        "`order_id` is in context. If you already know the `order_id`, prefer `get_order`.",
    )
)
@answers_failures
async def list_orders(
    start_date: StartDate = None,
    end_date: EndDate = None,
    iso_code: IsoCode = None,
    api: OperationClient = Depends(get_api),
) -> ListOrdersReply:
    """List previously placed Kyckr orders. Free to call. Optional filters: `start_date` and
    `end_date` (ISO 8601) and `iso_code` (jurisdiction). Orders are under `data.orders[]`, with
    paging in `data.pageNumber`, `data.pageSize` and `data.totalCount`. Each entry has the same
    shape as `get_order.data`. Use to reconcile when an order id is not in context.
    """
    response = await api.call(
        operations.GET_ORDER, startDate=start_date, endDate=end_date, isoCode=iso_code
    )
    body = response.model_dump()
    for order in _orders(body.get("data")):
        order.pop("links", None)
    return ListOrdersReply.model_validate({**body, "success": True})


def _orders(data: object) -> list[dict[str, object]]:
    page = data.get("orders") if isinstance(data, dict) else data
    return [order for order in page if isinstance(order, dict)] if isinstance(page, list) else []
