# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-21T12:09:32+00:00

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column


class Base(DeclarativeBase):
    """Every table's model subclasses it, so `alembic revision --autogenerate` sees it."""


class PositionRow(Base):
    """One holding of one ticker in a portfolio, owned by the user who signed in."""

    __tablename__: str = "positions"

    owner: Mapped[str] = mapped_column(String(255), primary_key=True)
    portfolio: Mapped[str] = mapped_column(String(64), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    # Float keeps the demo short. An MCP that stores real money uses Numeric and Decimal.
    quantity: Mapped[float] = mapped_column(Float)
    cost_basis: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
