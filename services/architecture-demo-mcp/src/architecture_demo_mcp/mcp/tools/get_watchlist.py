from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_types import ToolAnnotations

from architecture_demo_mcp.contexts import watchlists
from architecture_demo_mcp.mcp.dependencies import get_persistence
from architecture_demo_mcp.mcp.dependencies import get_upstream
from architecture_demo_mcp.mcp.inputs.watchlist_name import WatchlistName
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import Upstream


@tool(
    title="Get Watchlist",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
async def get_watchlist(
    watchlist: WatchlistName,
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
) -> list[watchlists.WatchedAsset]:
    """List the tickers on a watchlist, oldest first, each with its latest price.

    A ticker IEX does not quote is listed without a price. An unknown watchlist is empty.
    """
    return await watchlists.get_watchlist(
        upstream=upstream, persistence=persistence, watchlist=watchlist
    )
