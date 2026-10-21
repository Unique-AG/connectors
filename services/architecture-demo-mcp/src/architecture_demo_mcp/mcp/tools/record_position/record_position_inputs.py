from typing import Annotated

from pydantic import Field
from pydantic import StringConstraints

PortfolioName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
    Field(description="The portfolio to hold the position in, such as `retirement`."),
]
Quantity = Annotated[
    float,
    Field(gt=0, description="How many shares or units are held, replacing any earlier quantity."),
]
CostBasis = Annotated[
    float,
    Field(gt=0, description="What one share or unit cost on average, in the ticker's currency."),
]
