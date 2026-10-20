from datetime import datetime

from pydantic import BaseModel


class AddedToWatchlist(BaseModel):
    watchlist: str
    ticker: str
    name: str | None
    exchange: str | None
    note: str | None
    added_at: datetime


class WatchlistRejectedError(Exception):
    """The ticker breaks a watchlist rule, so nothing was stored."""
