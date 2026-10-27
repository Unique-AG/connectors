from datetime import date

from pydantic import BaseModel
from pydantic import Field


class PortfolioValuation(BaseModel):
    portfolio: str
    positions: list[ValuedPosition]
    cost: float = Field(description="What every position cost, quantity times cost basis.")
    market_value: float = Field(description="Every priced position at its latest close.")
    unrealized_pnl: float = Field(
        description="Market value less the cost of the positions it prices."
    )
    unrealized_return: float | None = Field(
        description="Unrealized P&L over the cost of the priced positions, 0.1 for 10%."
    )


class ValuedPosition(BaseModel):
    ticker: str
    quantity: float
    cost_basis: float
    last_close: float | None = Field(description="Null when Tiingo has no price for the ticker.")
    last_close_date: date | None
    market_value: float | None
    unrealized_pnl: float | None
    weight: float | None = Field(description="Share of the portfolio's market value, 0.25 for 25%.")
