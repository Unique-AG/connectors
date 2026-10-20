from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_types import ToolAnnotations

from architecture_demo_mcp.contexts import watchlists
from architecture_demo_mcp.mcp.dependencies import get_persistence
from architecture_demo_mcp.mcp.dependencies import get_upstream
from architecture_demo_mcp.mcp.inputs.ticker import Ticker
from architecture_demo_mcp.mcp.inputs.watchlist_name import WatchlistName
from architecture_demo_mcp.mcp.tools.add_to_watchlist.add_to_watchlist_inputs import Note
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import Upstream


@tool(
    title="Add To Watchlist",
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
    ),
)
async def add_to_watchlist(
    watchlist: WatchlistName,
    ticker: Ticker,
    note: Note = None,
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
) -> watchlists.AddedToWatchlist:
    """Put a ticker on a watchlist, creating the watchlist with its first ticker.

    A watchlist holds at most 20 tickers, each once. Tiingo must know the ticker.
    """
    entry = watchlists.AddToWatchlistInput(watchlist=watchlist, ticker=ticker, note=note)
    try:
        return await watchlists.add_to_watchlist(
            upstream=upstream, persistence=persistence, entry=entry
        )
    except watchlists.WatchlistRejectedError as error:
        raise ToolError(str(error)) from error
