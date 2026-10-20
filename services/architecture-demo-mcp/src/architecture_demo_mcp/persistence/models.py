from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column


class Base(DeclarativeBase):
    """Every table's model subclasses it, so `alembic revision --autogenerate` sees it."""


class WatchlistEntryRow(Base):
    """Every user of the server shares a watchlist, as the table has no owner column yet.

    Once auth lands, the owner joins the primary key.
    """

    __tablename__: str = "watchlist_entries"

    watchlist: Mapped[str] = mapped_column(String(64), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    note: Mapped[str | None] = mapped_column(String(200))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
