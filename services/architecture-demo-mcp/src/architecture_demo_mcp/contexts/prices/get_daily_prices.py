from datetime import date
from typing import Literal

from architecture_demo_mcp.contexts.prices.models import DailyPrice
from architecture_demo_mcp.contexts.prices.models import DailyPrices
from architecture_demo_mcp.upstream import DailyPriceBar
from architecture_demo_mcp.upstream import GET_DAILY_PRICES
from architecture_demo_mcp.upstream import GetDailyPricesPath
from architecture_demo_mcp.upstream import GetDailyPricesQuery
from architecture_demo_mcp.upstream import GetDailyPricesRequest
from architecture_demo_mcp.upstream import Upstream

type ResampleFrequency = Literal["daily", "weekly", "monthly", "annually"]


async def get_daily_prices(
    *,
    upstream: Upstream,
    ticker: str,
    start_date: date | None,
    end_date: date | None,
    resample_freq: ResampleFrequency | None,
) -> DailyPrices:
    """The ticker's prices per period, oldest first, titled by what they cover so a chat can
    cite them. Without either date Tiingo sends the latest trading day alone.
    """
    bars = await upstream.call(
        GET_DAILY_PRICES,
        GetDailyPricesRequest(
            path=GetDailyPricesPath(ticker=ticker),
            query=GetDailyPricesQuery(
                start_date=start_date, end_date=end_date, resample_freq=resample_freq
            ),
        ),
    )
    prices = [price for bar in bars if (price := _daily_price(bar=bar)) is not None]
    return DailyPrices(
        title=_title(ticker=ticker, frequency=resample_freq or "daily", prices=prices),
        ticker=ticker,
        prices=prices,
    )


def _daily_price(*, bar: DailyPriceBar) -> DailyPrice | None:
    """None for a bar Tiingo sent without a date, which no period can be placed by."""
    if bar.date is None:
        return None
    # Tiingo sends a date as midnight UTC, such as 2026-10-19T00:00:00.000Z.
    return DailyPrice(
        date=date.fromisoformat(bar.date[:10]),
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        adj_open=bar.adj_open,
        adj_high=bar.adj_high,
        adj_low=bar.adj_low,
        adj_close=bar.adj_close,
        adj_volume=bar.adj_volume,
        div_cash=bar.div_cash,
        split_factor=bar.split_factor,
    )


def _title(*, ticker: str, frequency: ResampleFrequency, prices: list[DailyPrice]) -> str:
    """Such as `AAPL daily prices, 2026-11-02 to 2026-11-20`, from the dates Tiingo sent. Tiingo
    dates a longer period by its last day: `AAPL weekly prices, periods ending 2026-11-06 to
    2026-11-20`.
    """
    name = f"{ticker} {frequency} prices"
    if not prices:
        return name
    first, last = prices[0].date, prices[-1].date
    dates = str(first) if first == last else f"{first} to {last}"
    if frequency == "daily":
        return f"{name}, {dates}"
    ending = "period ending" if first == last else "periods ending"
    return f"{name}, {ending} {dates}"
