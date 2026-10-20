from architecture_demo_mcp.contexts.assets import get_asset
from architecture_demo_mcp.contexts.watchlists.commands.add_to_watchlist.inputs import (
    AddToWatchlistInput,
)
from architecture_demo_mcp.contexts.watchlists.commands.add_to_watchlist.outputs import (
    AddedToWatchlist,
)
from architecture_demo_mcp.contexts.watchlists.commands.add_to_watchlist.outputs import (
    WatchlistRejectedError,
)
from architecture_demo_mcp.persistence import add_watchlist_entry
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.persistence import WatchlistRefusal
from architecture_demo_mcp.upstream import Upstream


async def add_to_watchlist(
    *, upstream: Upstream, persistence: Persistence, entry: AddToWatchlistInput
) -> AddedToWatchlist:
    asset = await get_asset(upstream=upstream, ticker=entry.ticker)
    stored = await add_watchlist_entry(
        persistence=persistence,
        watchlist=entry.watchlist,
        ticker=asset.ticker,
        note=entry.note,
        capacity=_MAX_TICKERS,
    )
    if isinstance(stored, WatchlistRefusal):
        raise _rejection(refusal=stored, ticker=asset.ticker, watchlist=entry.watchlist)
    return AddedToWatchlist(
        watchlist=stored.watchlist,
        ticker=stored.ticker,
        name=asset.name,
        exchange=asset.exchange,
        note=stored.note,
        added_at=stored.added_at,
    )


def _rejection(*, refusal: WatchlistRefusal, ticker: str, watchlist: str) -> WatchlistRejectedError:
    match refusal:
        case WatchlistRefusal.ALREADY_WATCHED:
            return WatchlistRejectedError(f"{ticker} is already on {watchlist}.")
        case WatchlistRefusal.FULL:
            return WatchlistRejectedError(
                f"{watchlist} already holds {_MAX_TICKERS} tickers. Remove one first."
            )


_MAX_TICKERS = 20
