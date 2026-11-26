from kyckr_mcp.contexts.orders.documents import with_document
from kyckr_mcp.contexts.orders.models import Order
from kyckr_mcp.contexts.orders.models import OrderReply
from kyckr_mcp.upstream import POST_ORDERS
from kyckr_mcp.upstream import PostOrdersBody
from kyckr_mcp.upstream import PostOrdersRequest
from kyckr_mcp.upstream import PostOrdersResponse
from kyckr_mcp.upstream import Upstream


async def create_document_order(
    *,
    upstream: Upstream,
    kyckr_id: str,
    product_id: str,
    customer_reference: str | None,
    contact_email: str | None,
) -> OrderReply:
    defaults = {"customer_reference": customer_reference, "contact_email": contact_email}
    response = await upstream.call(
        POST_ORDERS,
        PostOrdersRequest(
            body=PostOrdersBody(
                kyckr_id=kyckr_id,
                product_id=product_id,
                # A field set to None is sent as null, so a default nobody configured is left out.
                **{name: value for name, value in defaults.items() if value is not None},
            )
        ),
    )
    reply = OrderReply.model_validate(response)
    return await with_document(
        upstream=upstream, reply=reply.model_copy(update={"data": _created_order(response)})
    )


def _created_order(response: PostOrdersResponse) -> Order | None:
    """The order Kyckr created, whose id and status may come at the top level instead."""
    if response.data is None and response.order_id is None and response.status is None:
        return None
    order = Order.model_validate(response.data or {})
    return order.model_copy(
        update={
            "order_id": order.order_id if order.order_id is not None else response.order_id,
            "status": order.status if order.status is not None else response.status,
        }
    )
