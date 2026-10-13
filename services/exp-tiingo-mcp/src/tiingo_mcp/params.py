from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, Any

from pydantic import BeforeValidator, Field

LookbackDays = Annotated[int, Field(ge=1, le=366)]


def parse_tiingo_date(value: Any) -> Any:  # noqa: ANN401
    """Tiingo sends dates as ISO strings, e.g. 2024-12-31T00:00:00.000Z."""
    return datetime.fromisoformat(value).date() if isinstance(value, str) else value


if TYPE_CHECKING:
    StrDate = date | str  # what a model accepts; it always holds a date
else:
    StrDate = Annotated[date, BeforeValidator(parse_tiingo_date)]
