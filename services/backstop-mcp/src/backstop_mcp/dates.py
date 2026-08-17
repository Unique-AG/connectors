"""Lenient calendar-date parsing for Backstop date / timestamp spellings."""

from datetime import date, datetime
from typing import Annotated

from pydantic import BeforeValidator


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


LenientDate = Annotated[date | None, BeforeValidator(parse_lenient_date)]
