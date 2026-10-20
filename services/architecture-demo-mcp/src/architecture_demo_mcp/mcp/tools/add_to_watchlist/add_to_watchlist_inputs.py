from typing import Annotated

from pydantic import Field

Note = Annotated[
    str | None,
    Field(
        max_length=200,
        description="Why the user watches the ticker, shown beside it in the watchlist. Pass "
        "it only when the user gives a reason.",
    ),
]
