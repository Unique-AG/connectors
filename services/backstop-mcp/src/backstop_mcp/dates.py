"""Lenient calendar-date and timestamp parsing for Backstop date / timestamp spellings."""

from datetime import date, datetime, time
from typing import Annotated

from pydantic import BeforeValidator, TypeAdapter, ValidationError

_datetime_adapter: TypeAdapter[datetime] = TypeAdapter(datetime)


def parse_lenient_date(value: object) -> date | None:
    """Coerce Backstop date/timestamp spellings to a calendar day, or None if unparseable.

    Accepts `date` / `datetime` objects, ISO dates, ISO datetimes, and non-zero-padded
    `Y-M-D` forms (`2026-9-1`) that `date.fromisoformat` rejects.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10] if "T" in text or " " in text else text)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    parts = text.split("-")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        year, month, day = (int(part) for part in parts)
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def parse_lenient_datetime(value: object) -> datetime | None:
    """Coerce Backstop timestamp spellings to a datetime, or None if unparseable.

    Accepts `datetime` / `date` objects and strings pydantic already knows how to parse,
    including Backstop's colon-less offset (`2026-01-10T00:00:00.000-0500`). Junk, blank,
    and non-string scalars become None rather than failing the record.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return _datetime_adapter.validate_python(text)
    except ValidationError:
        return None


LenientDate = Annotated[date | None, BeforeValidator(parse_lenient_date)]
LenientDatetime = Annotated[datetime | None, BeforeValidator(parse_lenient_datetime)]
