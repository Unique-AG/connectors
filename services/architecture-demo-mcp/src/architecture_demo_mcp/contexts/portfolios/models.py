from datetime import date

from pydantic import BaseModel
from pydantic import Field


class PortfolioValuation(BaseModel):
    portfolio: str = Field(description="The name the user gave the portfolio.")
    positions: list[ValuedPosition] = Field(description="One per ticker the portfolio holds.")
    cost: float = Field(description="What every position cost, quantity times cost basis.")
    market_value: float = Field(description="Every priced position at its latest close.")
    unrealized_pnl: float = Field(
        description="Market value less the cost of the positions it prices."
    )
    unrealized_return: float | None = Field(
        description="Unrealized P&L over the cost of the priced positions, 0.1 for 10%."
    )


class ValuedPosition(BaseModel):
    ticker: str = Field(description="The ticker as Tiingo lists it.")
    quantity: float = Field(description="How many shares or units the user holds.")
    cost_basis: float = Field(description="What one share or unit cost.")
    last_close: float | None = Field(description="Null when Tiingo has no price for the ticker.")
    last_close_date: date | None = Field(description="The day of `last_close`.")
    market_value: float | None = Field(description="Quantity times the last close.")
    unrealized_pnl: float | None = Field(description="Market value less quantity times cost basis.")
    weight: float | None = Field(description="Share of the portfolio's market value, 0.25 for 25%.")
