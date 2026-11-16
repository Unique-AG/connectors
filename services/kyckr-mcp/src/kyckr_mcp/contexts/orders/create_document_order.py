from kyckr_mcp.contexts.orders.documents import created_order
from kyckr_mcp.contexts.orders.documents import order_result
from kyckr_mcp.contexts.orders.models import OrderResult
from kyckr_mcp.upstream import POST_ORDERS
from kyckr_mcp.upstream import PostOrdersBody
from kyckr_mcp.upstream import PostOrdersRequest
from kyckr_mcp.upstream import Upstream


async def create_document_order(
    *,
    upstream: Upstream,
    kyckr_id: str,
    product_id: str,
    customer_reference: str | None,
    contact_email: str | None,
) -> OrderResult:
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
    return await order_result(upstream=upstream, response=response, order=created_order(response))
