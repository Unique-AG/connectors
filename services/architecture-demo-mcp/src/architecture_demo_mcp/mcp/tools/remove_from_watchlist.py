from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_types import ToolAnnotations

from architecture_demo_mcp.contexts import watchlists
from architecture_demo_mcp.mcp.dependencies import get_persistence
from architecture_demo_mcp.mcp.inputs.ticker import Ticker
from architecture_demo_mcp.mcp.inputs.watchlist_name import WatchlistName
from architecture_demo_mcp.persistence import Persistence


@tool(
    title="Remove From Watchlist",
    annotations=ToolAnnotations(
        read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
async def remove_from_watchlist(
    watchlist: WatchlistName,
    ticker: Ticker,
    persistence: Persistence = Depends(get_persistence),
) -> watchlists.RemovedFromWatchlist:
    """Take a ticker off a watchlist, with its note. `removed` is false if it was not on it."""
    return await watchlists.remove_from_watchlist(
        persistence=persistence, watchlist=watchlist, ticker=ticker
    )
