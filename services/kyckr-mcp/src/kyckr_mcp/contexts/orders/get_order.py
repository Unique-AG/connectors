from kyckr_mcp.contexts.orders.documents import as_order
from kyckr_mcp.contexts.orders.documents import order_result
from kyckr_mcp.contexts.orders.models import OrderResult
from kyckr_mcp.upstream import GET_ORDERS_ORDER_ID
from kyckr_mcp.upstream import GetOrdersOrderIdPath
from kyckr_mcp.upstream import GetOrdersOrderIdRequest
from kyckr_mcp.upstream import Upstream


async def get_order(*, upstream: Upstream, order_id: str) -> OrderResult:
    response = await upstream.call(
        GET_ORDERS_ORDER_ID, GetOrdersOrderIdRequest(path=GetOrdersOrderIdPath(order_id=order_id))
    )
    return await order_result(
        upstream=upstream, response=response, order=as_order(response.data), order_id=order_id
    )
