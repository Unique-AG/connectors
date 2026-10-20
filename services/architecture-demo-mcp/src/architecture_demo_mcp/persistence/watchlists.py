from datetime import datetime
from datetime import UTC

from pydantic import BaseModel
from sqlalchemy import select

from architecture_demo_mcp.persistence.models import WatchlistEntryRow
from architecture_demo_mcp.persistence.persistence import Persistence


class WatchlistEntry(BaseModel):
    watchlist: str
    ticker: str
    note: str | None
    added_at: datetime


async def list_watchlist(*, persistence: Persistence, watchlist: str) -> list[WatchlistEntry]:
    async with persistence.database() as session:
        rows = await session.scalars(
            select(WatchlistEntryRow)
            .where(WatchlistEntryRow.watchlist == watchlist)
            .order_by(WatchlistEntryRow.added_at)
        )
        return [_entry(row) for row in rows]


async def add_watchlist_entry(
    *, persistence: Persistence, watchlist: str, ticker: str, note: str | None
) -> WatchlistEntry:
    row = WatchlistEntryRow(
        watchlist=watchlist, ticker=ticker, note=note, added_at=datetime.now(UTC)
    )
    async with persistence.database() as session, session.begin():
        session.add(row)
    return _entry(row)


async def remove_watchlist_entry(*, persistence: Persistence, watchlist: str, ticker: str) -> bool:
    """False when the ticker was not on the watchlist."""
    async with persistence.database() as session, session.begin():
        row = await session.get(WatchlistEntryRow, (watchlist, ticker))
        if row is None:
            return False
        await session.delete(row)
    return True


def _entry(row: WatchlistEntryRow) -> WatchlistEntry:
    return WatchlistEntry(
        watchlist=row.watchlist, ticker=row.ticker, note=row.note, added_at=row.added_at
    )
