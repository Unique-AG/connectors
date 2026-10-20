from typing import ClassVar

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class AddToWatchlistInput(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    watchlist: str = Field(min_length=1, max_length=64)
    ticker: str = Field(min_length=1, max_length=32)
    note: str | None = Field(
        default=None,
        max_length=200,
        description="Why the user watches the ticker, shown beside it in the watchlist.",
    )
