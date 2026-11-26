from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_observability import trace_arguments
from mcp_types import ToolAnnotations
from pydantic import Field

from architecture_demo_mcp import contexts
from architecture_demo_mcp.mcp.dependencies import get_upstream
from architecture_demo_mcp.mcp.inputs.ticker import Ticker
from architecture_demo_mcp.upstream import Upstream


@tool(
    title="Get IEX Top of Book",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=False, open_world_hint=True),
)
@trace_arguments("tickers")
async def get_iex_top_of_book(
    *,
    tickers: Annotated[
        list[Ticker] | None,
        Field(description="The tickers to quote. Leave it out for every ticker IEX quotes."),
    ] = None,
    upstream: Upstream = Depends(get_upstream),
) -> contexts.TopOfBook:
    """Get the latest IEX quote of each ticker: last sale, bid and ask, today's open, high and low,
    and the previous close. The result's `title` names the tickers: cite the quotes by it.
    """
    return await contexts.get_top_of_book(upstream=upstream, tickers=tickers or [])
