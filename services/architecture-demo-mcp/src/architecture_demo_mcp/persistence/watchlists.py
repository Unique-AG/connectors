from datetime import datetime
from datetime import UTC
from enum import StrEnum

from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects import sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from architecture_demo_mcp.persistence.models import WatchlistEntryRow
from architecture_demo_mcp.persistence.persistence import Persistence


class WatchlistEntry(BaseModel):
    watchlist: str
    ticker: str
    note: str | None
    added_at: datetime


class WatchlistRefusal(StrEnum):
    """Why `add_watchlist_entry` stored nothing."""

    ALREADY_WATCHED = "already_watched"
    FULL = "full"


async def list_watchlist(*, persistence: Persistence, watchlist: str) -> list[WatchlistEntry]:
    async with persistence.database() as session:
        rows = await session.scalars(
            select(WatchlistEntryRow)
            .where(WatchlistEntryRow.watchlist == watchlist)
            .order_by(WatchlistEntryRow.added_at)
        )
        return [_entry(row) for row in rows]


async def add_watchlist_entry(
    *, persistence: Persistence, watchlist: str, ticker: str, note: str | None, capacity: int
) -> WatchlistEntry | WatchlistRefusal:
    """Adds the ticker unless it is already on the watchlist or the watchlist holds `capacity`.

    Two adds to one watchlist at once would both see room for one more, so the count and the
    insert run in one transaction under a lock on the watchlist.
    """
    entry = WatchlistEntry(
        watchlist=watchlist, ticker=ticker, note=note, added_at=datetime.now(UTC)
    )
    async with persistence.database() as session, session.begin():
        await _lock_watchlist(session=session, watchlist=watchlist)
        watched = set(
            await session.scalars(
                select(WatchlistEntryRow.ticker).where(WatchlistEntryRow.watchlist == watchlist)
            )
        )
        if ticker in watched:
            return WatchlistRefusal.ALREADY_WATCHED
        if len(watched) >= capacity:
            return WatchlistRefusal.FULL
        inserted = await session.scalar(
            _insert(session)
            .values(entry.model_dump())
            .on_conflict_do_nothing()
            .returning(WatchlistEntryRow.ticker)
        )
    return entry if inserted is not None else WatchlistRefusal.ALREADY_WATCHED


async def remove_watchlist_entry(*, persistence: Persistence, watchlist: str, ticker: str) -> bool:
    """False when the ticker was not on the watchlist."""
    async with persistence.database() as session, session.begin():
        removed = await session.scalar(
            delete(WatchlistEntryRow)
            .where(WatchlistEntryRow.watchlist == watchlist, WatchlistEntryRow.ticker == ticker)
            .returning(WatchlistEntryRow.ticker)
        )
    return removed is not None


async def _lock_watchlist(*, session: AsyncSession, watchlist: str) -> None:
    """Held until the transaction ends. SQLite serialises every write, so it needs no lock."""
    if _dialect(session) == "postgresql":
        await session.execute(
            select(
                func.pg_advisory_xact_lock(
                    func.hashtext(WatchlistEntryRow.__tablename__), func.hashtext(watchlist)
                )
            )
        )


def _insert(session: AsyncSession) -> postgresql.Insert | sqlite.Insert:
    """`on_conflict_do_nothing` is dialect-specific in SQLAlchemy. The tests run on SQLite."""
    if _dialect(session) == "sqlite":
        return sqlite.insert(WatchlistEntryRow)
    return postgresql.insert(WatchlistEntryRow)


def _dialect(session: AsyncSession) -> str:
    return session.get_bind().dialect.name


def _entry(row: WatchlistEntryRow) -> WatchlistEntry:
    return WatchlistEntry(
        watchlist=row.watchlist, ticker=row.ticker, note=row.note, added_at=row.added_at
    )
