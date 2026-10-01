"""Inclusive date window: an omitted start is one year before the end, an omitted end is today."""

from datetime import date

__all__ = ["date_window"]


def _add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def date_window(
    start_date: date | None, end_date: date | None, *, today: date
) -> tuple[date, date]:
    until = end_date if end_date is not None else today
    since = start_date if start_date is not None else _add_years(until, -1)
    if since > until:
        raise ValueError("start_date must not be after end_date")
    return since, until
