from pydantic import Field

from kyckr_mcp.contexts.orders.models import Order
from kyckr_mcp.contexts.replies import KyckrModel
from kyckr_mcp.contexts.replies import Reply
from kyckr_mcp.upstream import GET_ORDER
from kyckr_mcp.upstream import GetOrderQuery
from kyckr_mcp.upstream import GetOrderRequest
from kyckr_mcp.upstream import OrdersPage
from kyckr_mcp.upstream import Upstream


async def list_orders(
    *,
    upstream: Upstream,
    start_date: str | None,
    end_date: str | None,
    iso_code: str | None,
) -> OrdersReply:
    query = GetOrderQuery(start_date=start_date, end_date=end_date, iso_code=iso_code)
    response = await upstream.call(GET_ORDER, GetOrderRequest(query=query))
    if isinstance(response.data, list):
        response = response.model_copy(
            update={"data": OrdersPage.model_validate({"orders": response.data})}
        )
    return OrdersReply.model_validate(response)


class OrderList(KyckrModel):
    """A page of orders."""

    page_number: int | None = Field(None, description="The number of this page.")
    page_size: int | None = Field(None, description="The most orders a page holds.")
    total_count: int | None = Field(None, description="How many orders match, on every page.")
    orders: list[Order] | None = Field(None, description="The orders on this page.")


class OrdersReply(Reply):
    """The orders placed with Kyckr."""

    data: OrderList | None = Field(None, description="A page of orders.")
