from typing import Annotated

from pydantic import Field
from pydantic import StringConstraints

Ticker = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, min_length=1, max_length=32),
    Field(description="A stock or ETF ticker such as `AAPL`, as `search_assets` returns it."),
]
