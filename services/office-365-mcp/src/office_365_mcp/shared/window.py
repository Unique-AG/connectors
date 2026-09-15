"""What a time window means, for every tool on the surface that takes one.

One rule: the bound a caller names is inside the window. A bare date names a whole day, so a lower
bound opens at its first instant and an upper bound closes at its last, and the same date in both
bounds is that one day. A moment names a second, so both bounds are that second. `zone` settles
what a naive moment and a bare date mean; an offset the caller wrote always wins over it. How a
tool RENDERS an instant stays with the tool: OData, `calendarView` and KQL each spell one
differently.
"""

from datetime import UTC, date, datetime, time, tzinfo


def as_utc(moment: datetime) -> datetime:
    """The moment as an aware datetime, reading a naive one as UTC rather than as local time.

    TRAP: this only labels. An aware moment keeps the zone it arrived in, so rendering the result
    as a literal ending in `Z` moves the bound by that offset; `opens_at`/`closes_at` convert.
    """
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def opens_at(bound: date | datetime, *, zone: tzinfo = UTC) -> datetime:
    """The first instant the lower bound admits.

    `datetime` is checked before `date` and must be: it subclasses `date`, so the other order reads
    every moment as the day it falls on and silently discards the time that was asked for.
    """
    if isinstance(bound, datetime):
        return _aware(bound, zone).astimezone(zone)
    return datetime.combine(bound, time.min, tzinfo=zone)


def closes_at(bound: date | datetime, *, zone: tzinfo = UTC) -> datetime:
    """The last instant the upper bound admits.

    A tool whose wire form is a half-open `lt` renders `opens_at(day + 1)` instead and uses this
    only to compare the two bounds: comparing a rendered `lt` bound calls one day backwards.
    """
    if isinstance(bound, datetime):
        return _aware(bound, zone).astimezone(zone)
    return datetime.combine(bound, time.max, tzinfo=zone)


def runs_backwards(
    after: date | datetime | None, before: date | datetime | None, *, zone: tzinfo = UTC
) -> bool:
    """Whether the two bounds name a window that holds nothing.

    Compared as instants, not as the caller's values: the arguments can be a date and a moment, and
    Python refuses to order those against each other. Equal bounds are not backwards.
    """
    if after is None or before is None:
        return False
    return opens_at(after, zone=zone) > closes_at(before, zone=zone)


def _aware(moment: datetime, zone: tzinfo) -> datetime:
    """A naive moment read in `zone`; an aware one left as the instant it already names.

    The one place `zone` changes a meaning rather than a rendering.
    """
    return moment.replace(tzinfo=zone) if moment.tzinfo is None else moment
