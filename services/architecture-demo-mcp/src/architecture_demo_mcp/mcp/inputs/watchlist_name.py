from typing import Annotated

from pydantic import Field
from pydantic import StringConstraints

WatchlistName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    Field(
        description="The watchlist's name, such as `tech`. Every user of this server shares "
        "the watchlists until it has auth."
    ),
]
