import asyncio
import logging

from architecture_demo_mcp.contexts.portfolios.models import PortfolioValuation
from architecture_demo_mcp.contexts.portfolios.models import ValuedPosition
from architecture_demo_mcp.contexts.prices import DailyClose
from architecture_demo_mcp.contexts.prices import get_latest_close
from architecture_demo_mcp.persistence import list_positions
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.persistence import Position
from architecture_demo_mcp.upstream import Upstream
from architecture_demo_mcp.upstream import UpstreamError

_logger = logging.getLogger(__name__)
# A large portfolio is priced a few tickers at a time, so it does not send Tiingo a burst of
# requests at once.
_CONCURRENT_PRICE_REQUESTS = 4


async def value_portfolio(
    *, upstream: Upstream, persistence: Persistence, owner: str, portfolio: str
) -> PortfolioValuation:
    """Each of the owner's positions in the portfolio at its latest close, with the totals.

    A position Tiingo has no price for, or could not price just now, stays listed, unpriced and
    out of the P&L.
    """
    positions = await list_positions(persistence=persistence, owner=owner, portfolio=portfolio)
    requests = asyncio.Semaphore(_CONCURRENT_PRICE_REQUESTS)
    closes = await asyncio.gather(
        *(
            _latest_close_or_none(
                upstream=upstream,
                persistence=persistence,
                ticker=position.ticker,
                requests=requests,
            )
            for position in positions
        )
    )
    held = list(zip(positions, closes, strict=True))
    priced = [(position, close) for position, close in held if close is not None]
    priced_cost = sum(_cost(position=position) for position, _ in priced)
    market_value = sum(position.quantity * close.close for position, close in priced)
    return PortfolioValuation(
        portfolio=portfolio,
        positions=[
            _valued(position=position, close=close, portfolio_value=market_value)
            for position, close in held
        ],
        cost=round(sum(_cost(position=position) for position in positions), 2),
        market_value=round(market_value, 2),
        unrealized_pnl=round(market_value - priced_cost, 2),
        unrealized_return=round(market_value / priced_cost - 1, 6) if priced_cost else None,
    )


async def _latest_close_or_none(
    *, upstream: Upstream, persistence: Persistence, ticker: str, requests: asyncio.Semaphore
) -> DailyClose | None:
    async with requests:
        try:
            return await get_latest_close(upstream=upstream, persistence=persistence, ticker=ticker)
        except UpstreamError:
            _logger.warning(
                "Left %s unpriced: Tiingo did not answer its latest close", ticker, exc_info=True
            )
            return None


def _valued(
    *, position: Position, close: DailyClose | None, portfolio_value: float
) -> ValuedPosition:
    if close is None:
        return ValuedPosition(
            ticker=position.ticker,
            quantity=position.quantity,
            cost_basis=position.cost_basis,
            last_close=None,
            last_close_date=None,
            market_value=None,
            unrealized_pnl=None,
            weight=None,
        )
    market_value = position.quantity * close.close
    return ValuedPosition(
        ticker=position.ticker,
        quantity=position.quantity,
        cost_basis=position.cost_basis,
        last_close=close.close,
        last_close_date=close.date,
        market_value=round(market_value, 2),
        unrealized_pnl=round(market_value - _cost(position=position), 2),
        weight=round(market_value / portfolio_value, 6),
    )


def _cost(*, position: Position) -> float:
    return position.quantity * position.cost_basis
