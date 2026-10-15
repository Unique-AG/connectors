from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Annotated

from pydantic import BeforeValidator, Field

LookbackDays = Annotated[int, Field(ge=1, le=366)]
Ticker = Annotated[str, Field(min_length=1, description="Ticker of the asset, for example AAPL.")]


def since(lookback_days: int) -> str:
    return (date.today() - timedelta(days=lookback_days)).isoformat()


def _parse_tiingo_date(value: object) -> object:
    """Tiingo sends dates as ISO strings, e.g. 2024-12-31T00:00:00.000Z."""
    return datetime.fromisoformat(value).date() if isinstance(value, str) else value


if TYPE_CHECKING:
    StrDate = date | str  # what a model accepts; it always holds a date
else:
    StrDate = Annotated[date, BeforeValidator(_parse_tiingo_date)]
