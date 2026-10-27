from datetime import date
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_types import ToolAnnotations
from pydantic import Field

from architecture_demo_mcp import contexts
from architecture_demo_mcp.mcp.dependencies import get_persistence
from architecture_demo_mcp.mcp.dependencies import get_upstream
from architecture_demo_mcp.mcp.inputs.ticker import Ticker
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import Upstream


@tool(
    title="Get Price Performance",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
async def get_price_performance(
    *,
    ticker: Ticker,
    start_date: Annotated[date, Field(description="The first day of the period, `YYYY-MM-DD`.")],
    end_date: Annotated[
        date | None,
        Field(description="The last day of the period, `YYYY-MM-DD`. Leave it out for today."),
    ] = None,
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
) -> contexts.PricePerformance:
    """Summarize how a ticker's price moved over a period: total return, annualized volatility,
    maximum drawdown and the high and low, from closes adjusted for splits and dividends.

    Call it to compare assets or judge risk. For the raw daily prices, call `get_daily_prices`.
    """
    try:
        return await contexts.get_price_performance(
            upstream=upstream,
            persistence=persistence,
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
        )
    except contexts.PerformanceUnavailableError as error:
        raise ToolError(str(error)) from error
