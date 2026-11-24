from datetime import date
from typing import Annotated

from pydantic import BaseModel
from pydantic import Field


class DailyClose(BaseModel):
    """One trading day, adjusted for splits and dividends so days compare across them."""

    date: date
    close: float
    high: float | None
    low: float | None


class DailyPrice(BaseModel):
    """One period's prices as Tiingo reports them, raw and adjusted for splits and dividends."""

    date: Annotated[date, Field(description="The day the period ends.")]
    open: float | None = Field(description="Opening price.")
    high: float | None = Field(description="Highest price.")
    low: float | None = Field(description="Lowest price.")
    close: float | None = Field(description="Closing price.")
    volume: int | None = Field(description="Shares traded.")
    adj_open: float | None = Field(description="Opening price adjusted for splits and dividends.")
    adj_high: float | None = Field(description="Highest price adjusted for splits and dividends.")
    adj_low: float | None = Field(description="Lowest price adjusted for splits and dividends.")
    adj_close: float | None = Field(description="Closing price adjusted for splits and dividends.")
    adj_volume: int | None = Field(description="Shares traded, adjusted for splits.")
    div_cash: float | None = Field(description="Dividend paid on the day, per share.")
    split_factor: float | None = Field(description="Split applied on the day, 1 when none.")


class DailyPrices(BaseModel):
    title: str = Field(
        description="The ticker, the period length and the dates covered, by which a chat cites it."
    )
    ticker: str = Field(description="The ticker the prices are for.")
    prices: list[DailyPrice] = Field(description="The periods, oldest first.")


class Quote(BaseModel):
    """A ticker's latest IEX quote."""

    ticker: str = Field(description="The ticker the quote is for.")
    timestamp: str | None = Field(description="When Tiingo last refreshed the quote.")
    last: float | None = Field(description="Last sale price on IEX.")
    tngo_last: float | None = Field(
        description="Tiingo's last price: the last sale, else the mid, else the previous close."
    )
    prev_close: float | None = Field(description="Previous trading day's close.")
    open: float | None = Field(description="Today's opening price.")
    high: float | None = Field(description="Today's highest price.")
    low: float | None = Field(description="Today's lowest price.")
    mid: float | None = Field(description="Midpoint of the bid and ask.")
    bid_price: float | None = Field(description="Best bid price.")
    bid_size: float | None = Field(description="Shares at the best bid.")
    ask_price: float | None = Field(description="Best ask price.")
    ask_size: float | None = Field(description="Shares at the best ask.")
    volume: int | None = Field(
        description="Shares traded today: on IEX during the day, then on every exchange once the "
        "official close is in."
    )


class TopOfBook(BaseModel):
    title: str = Field(description="The tickers quoted, by which a chat cites the quotes.")
    quotes: list[Quote] = Field(description="One quote per ticker.")
