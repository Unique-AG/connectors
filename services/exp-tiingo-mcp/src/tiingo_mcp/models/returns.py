from pydantic import BaseModel

from tiingo_mcp.params import StrDate


class ReturnPoint(BaseModel):
    date: StrDate
    return_pct: float


class ReturnSeries(BaseModel):
    ticker: str
    total_return_pct: float
    points: list[ReturnPoint]


class ReturnsChart(BaseModel):
    lookback_days: int
    start: StrDate
    end: StrDate
    series: list[ReturnSeries]
