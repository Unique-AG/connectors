from pydantic import BaseModel

from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.persistence import remove_watchlist_entry


async def remove_from_watchlist(
    *, persistence: Persistence, watchlist: str, ticker: str
) -> RemovedFromWatchlist:
    removed = await remove_watchlist_entry(
        persistence=persistence, watchlist=watchlist, ticker=ticker
    )
    return RemovedFromWatchlist(watchlist=watchlist, ticker=ticker, removed=removed)


class RemovedFromWatchlist(BaseModel):
    watchlist: str
    ticker: str
    removed: bool
    """False when the ticker was not on the watchlist."""
