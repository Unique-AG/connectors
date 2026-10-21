from datetime import datetime
from datetime import UTC

from pydantic import BaseModel

from architecture_demo_mcp.contexts.portfolios.models import PortfolioValuation
from architecture_demo_mcp.contexts.portfolios.value_portfolio import value_portfolio
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.persistence import Position
from architecture_demo_mcp.persistence import save_position
from architecture_demo_mcp.upstream import GET_DAILY_META
from architecture_demo_mcp.upstream import Upstream


async def record_position(
    *, upstream: Upstream, persistence: Persistence, owner: str, position: PositionInput
) -> PortfolioValuation:
    """Sets the owner's holding of a ticker in a portfolio, then values the whole portfolio.

    Only a ticker Tiingo has prices for is held, since no other could ever be valued.
    """
    meta = await upstream.call(GET_DAILY_META, ticker=position.ticker)
    if meta.endDate is None:
        raise PositionRejectedError(
            f"Tiingo has no prices for {position.ticker}, so a position in it cannot be valued."
        )
    await save_position(
        persistence=persistence,
        owner=owner,
        position=Position(
            portfolio=position.portfolio,
            ticker=meta.ticker.upper() if meta.ticker else position.ticker,
            quantity=position.quantity,
            cost_basis=position.cost_basis,
            updated_at=datetime.now(UTC),
        ),
    )
    return await value_portfolio(
        upstream=upstream, persistence=persistence, owner=owner, portfolio=position.portfolio
    )


class PositionRejectedError(Exception):
    """The position breaks a portfolio rule, so nothing was stored."""


class PositionInput(BaseModel):
    portfolio: str
    ticker: str
    quantity: float
    cost_basis: float
