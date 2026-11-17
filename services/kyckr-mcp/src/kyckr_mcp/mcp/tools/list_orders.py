from fastmcp.dependencies import Depends
from fastmcp.tools import tool

from kyckr_mcp import contexts
from kyckr_mcp.mcp.dependencies import get_upstream
from kyckr_mcp.mcp.hints import FREE_READ
from kyckr_mcp.mcp.hints import tool_options
from kyckr_mcp.mcp.inputs.company import IsoCode
from kyckr_mcp.mcp.inputs.order import EndDate
from kyckr_mcp.mcp.inputs.order import StartDate
from kyckr_mcp.mcp.responses.failures import answers_failures
from kyckr_mcp.mcp.responses.replies import answer
from kyckr_mcp.mcp.responses.replies import Reply
from kyckr_mcp.upstream import Upstream


@tool(
    **tool_options(
        "List Orders",
        FREE_READ,
        icon="file-text",
        system_prompt=(
            "Use to find a prior order when the user references one by company or date but no "
            "`order_id` is in context. If you already know the `order_id`, prefer `get_order`."
        ),
    )
)
@answers_failures
async def list_orders(
    start_date: StartDate = None,
    end_date: EndDate = None,
    iso_code: IsoCode = None,
    *,
    upstream: Upstream = Depends(get_upstream),
) -> Reply:
    """List previously placed Kyckr orders. Free to call. Optional filters: `start_date` and
    `end_date` (ISO 8601) and `iso_code` (jurisdiction). Orders are under `data.orders[]`, with
    paging in `data.pageNumber`, `data.pageSize` and `data.totalCount`. Each entry has the same
    shape as `get_order.data`. Use to reconcile when an order id is not in context.
    """
    result = await contexts.list_orders(
        upstream=upstream, start_date=start_date, end_date=end_date, iso_code=iso_code
    )
    return answer(Reply, result)
