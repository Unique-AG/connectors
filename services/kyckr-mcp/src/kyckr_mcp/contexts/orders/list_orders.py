from kyckr_mcp.upstream import GET_ORDER
from kyckr_mcp.upstream import GetOrderQuery
from kyckr_mcp.upstream import GetOrderRequest
from kyckr_mcp.upstream import GetOrderResponse
from kyckr_mcp.upstream import OrdersPage
from kyckr_mcp.upstream import Upstream


async def list_orders(
    *,
    upstream: Upstream,
    start_date: str | None,
    end_date: str | None,
    iso_code: str | None,
) -> GetOrderResponse:
    """A page of orders, without the download links of each."""
    query = GetOrderQuery(start_date=start_date, end_date=end_date, iso_code=iso_code)
    response = await upstream.call(GET_ORDER, GetOrderRequest(query=query))
    data = response.data
    for order in (data.orders if isinstance(data, OrdersPage) else data) or []:
        (order.model_extra or {}).pop("links", None)
    return response
