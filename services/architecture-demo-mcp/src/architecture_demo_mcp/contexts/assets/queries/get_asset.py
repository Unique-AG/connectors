from pydantic import BaseModel

from architecture_demo_mcp.upstream import GET_DAILY_META
from architecture_demo_mcp.upstream import Upstream


async def get_asset(*, upstream: Upstream, ticker: str) -> AssetDetails:
    meta = await upstream.call(GET_DAILY_META, ticker=ticker)
    return AssetDetails(
        ticker=meta.ticker or ticker,
        name=meta.name,
        description=meta.description,
        exchange=meta.exchangeCode,
        first_price_date=meta.startDate,
        last_price_date=meta.endDate,
    )


class AssetDetails(BaseModel):
    ticker: str
    name: str | None
    description: str | None
    exchange: str | None
    first_price_date: str | None
    last_price_date: str | None
