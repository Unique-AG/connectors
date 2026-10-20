from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_types import ToolAnnotations

from architecture_demo_mcp.contexts import quotes
from architecture_demo_mcp.mcp.dependencies import get_persistence
from architecture_demo_mcp.mcp.dependencies import get_upstream
from architecture_demo_mcp.mcp.inputs.ticker import Ticker
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import Upstream


@tool(
    title="Get Quote",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
async def get_quote(
    ticker: Ticker,
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
) -> quotes.Quote:
    """Read a stock's latest IEX price and its previous close, at most a minute old."""
    try:
        return await quotes.get_quote(upstream=upstream, persistence=persistence, ticker=ticker)
    except quotes.QuoteNotFoundError as error:
        raise ToolError(str(error)) from error
