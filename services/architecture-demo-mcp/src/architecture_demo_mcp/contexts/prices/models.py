from datetime import date

from pydantic import BaseModel


class DailyClose(BaseModel):
    """One trading day, adjusted for splits and dividends so days compare across them."""

    date: date
    close: float
    high: float | None
    low: float | None
