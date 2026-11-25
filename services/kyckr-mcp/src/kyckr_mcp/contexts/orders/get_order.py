from kyckr_mcp.contexts.orders.documents import with_document
from kyckr_mcp.contexts.orders.models import OrderReply
from kyckr_mcp.upstream import GET_ORDERS_ORDER_ID
from kyckr_mcp.upstream import GetOrdersOrderIdPath
from kyckr_mcp.upstream import GetOrdersOrderIdRequest
from kyckr_mcp.upstream import Upstream


async def get_order(*, upstream: Upstream, order_id: str) -> OrderReply:
    response = await upstream.call(
        GET_ORDERS_ORDER_ID, GetOrdersOrderIdRequest(path=GetOrdersOrderIdPath(order_id=order_id))
    )
    return await with_document(
        upstream=upstream, reply=OrderReply.model_validate(response), order_id=order_id
    )
