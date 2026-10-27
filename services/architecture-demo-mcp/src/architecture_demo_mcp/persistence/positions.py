from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import Executable
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects import sqlite
from sqlalchemy.ext.asyncio import AsyncSession

from architecture_demo_mcp.persistence.models import PositionRow
from architecture_demo_mcp.persistence.persistence import Persistence


class Position(BaseModel):
    portfolio: str
    ticker: str
    quantity: float
    cost_basis: float
    updated_at: datetime


async def save_position(*, persistence: Persistence, owner: str, position: Position) -> None:
    """Replaces the owner's holding of the ticker in the portfolio, or adds it."""
    async with persistence.database() as session, session.begin():
        await session.execute(
            _upsert(session=session, values={"owner": owner, **position.model_dump()})
        )


async def list_positions(*, persistence: Persistence, owner: str, portfolio: str) -> list[Position]:
    async with persistence.database() as session:
        rows = await session.scalars(
            select(PositionRow)
            .where(PositionRow.owner == owner, PositionRow.portfolio == portfolio)
            .order_by(PositionRow.ticker)
        )
        return [_position(row) for row in rows]


def _upsert(*, session: AsyncSession, values: dict[str, object]) -> Executable:
    """`on_conflict_do_update` is dialect-specific in SQLAlchemy. The tests run on SQLite."""
    key = [PositionRow.owner, PositionRow.portfolio, PositionRow.ticker]
    insert = sqlite.insert if session.get_bind().dialect.name == "sqlite" else postgresql.insert
    inserted = insert(PositionRow).values(values)
    updated = {column: inserted.excluded[column] for column in _UPDATED}
    return inserted.on_conflict_do_update(index_elements=key, set_=updated)


def _position(row: PositionRow) -> Position:
    return Position(
        portfolio=row.portfolio,
        ticker=row.ticker,
        quantity=row.quantity,
        cost_basis=row.cost_basis,
        updated_at=row.updated_at,
    )


_UPDATED = ("quantity", "cost_basis", "updated_at")
