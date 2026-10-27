from architecture_demo_mcp.contexts.prices.get_daily_closes import get_daily_closes
from architecture_demo_mcp.contexts.prices.models import DailyClose
from architecture_demo_mcp.persistence import Persistence
from architecture_demo_mcp.upstream import Upstream


async def get_latest_close(
    *, upstream: Upstream, persistence: Persistence, ticker: str
) -> DailyClose | None:
    """The last trading day Tiingo has for the ticker, or None when it has none."""
    closes = await get_daily_closes(
        upstream=upstream, persistence=persistence, ticker=ticker, start_date=None, end_date=None
    )
    return closes[-1] if closes else None
