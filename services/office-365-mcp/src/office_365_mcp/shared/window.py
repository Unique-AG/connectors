"""What a time window means, in one place, for every tool on the surface that takes one.

Four tools take a two-sided window — `outlook_list_mail`, `outlook_search_mail`,
`outlook_list_events` and `teams_search_messages` — and they reach three different Graph surfaces:
an OData `$filter`, required `calendarView` query arguments, and a KQL comparison. What they must
not disagree about is the bit a caller can see: what a bound MEANS.

One rule, and it is the whole module. **The bound a caller names is inside the window.** A bare
date names a whole day, so the lower bound opens at that day's first instant and the upper bound
closes at its last. A moment names a second, so both bounds are that second. This is why the same
date in both bounds is that single day rather than nothing at all: two first instants would
bracket an empty window, which is a caller's most obvious way to ask for one day and a wrong
answer nobody can see.

How a tool RENDERS an instant stays with the tool, because the three surfaces spell one differently
and cannot be unified: OData takes an unquoted ISO-8601 literal, `calendarView` takes one carrying
its own offset, and KQL takes one of four documented shapes. Only the meaning lives here.

`zone` is the one dial, and it settles what a *naive* moment and a bare date mean. It defaults to
UTC, which is right for every tool that has no zone of its own. `outlook_list_events` passes its
`time_zone`, because that argument is the caller saying which zone they are talking about and the
whole answer is already rendered in it — so a bare `2026-03-04` there is that local day and a
wall clock with no offset is that local time. An offset a caller wrote always wins over `zone`; it
already names an instant, and `zone` then only decides how it is rendered.

TRAP: `as_utc` supplies a missing zone and nothing else. It leaves an aware moment in the zone it
arrived in, which is correct for a comparison and wrong for rendering a literal that ends in `Z` —
that combination stamps UTC on a wall clock and moves the bound by the offset. `opens_at` and
`closes_at` convert, so a value from either is safe to compare AND safe to render.
"""

from datetime import UTC, date, datetime, time, tzinfo


def as_utc(moment: datetime) -> datetime:
    """The moment as an aware datetime, reading a naive one as UTC rather than as local time.

    Local time here is whichever zone the process happens to run in, which no caller chose and no
    answer names. This function only labels: see the module docstring before rendering its result.
    """
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


def opens_at(bound: date | datetime, *, zone: tzinfo = UTC) -> datetime:
    """The first instant the lower bound admits.

    `datetime` is checked before `date` and must be: it subclasses `date`, so the other order
    reads every moment as the day it falls on and silently discards the time that was asked for.
    """
    if isinstance(bound, datetime):
        return _aware(bound, zone).astimezone(zone)
    return datetime.combine(bound, time.min, tzinfo=zone)


def closes_at(bound: date | datetime, *, zone: tzinfo = UTC) -> datetime:
    """The last instant the upper bound admits.

    A bare date closes at `time.max`, so the whole of that day is inside the window. A tool whose
    wire form is a half-open `lt` renders `opens_at(day + 1)` instead and uses this only to compare
    the two bounds against each other — comparing a rendered `lt` bound would call a window of one
    day backwards.
    """
    if isinstance(bound, datetime):
        return _aware(bound, zone).astimezone(zone)
    return datetime.combine(bound, time.max, tzinfo=zone)


def runs_backwards(
    after: date | datetime | None, before: date | datetime | None, *, zone: tzinfo = UTC
) -> bool:
    """Whether the two bounds name a window that holds nothing.

    Compared as instants rather than as the caller's values, because the two arguments can be a
    date and a moment, and Python refuses to order those against each other. Equal bounds are not
    backwards: a moment in both names that one instant, and a date in both names that one day.
    """
    if after is None or before is None:
        return False
    return opens_at(after, zone=zone) > closes_at(before, zone=zone)


def _aware(moment: datetime, zone: tzinfo) -> datetime:
    """A naive moment read in `zone`; an aware one left as the instant it already names.

    This is the one place `zone` changes a meaning rather than a rendering, and it is why the
    parameter exists. A tool with no zone of its own leaves it at UTC. `outlook_list_events` has
    one — `time_zone`, which the caller states and every bound and row of that answer is rendered
    in — so a wall clock with no offset means that zone there, not UTC. Reading it as UTC would
    move a caller's `09:00` by their own offset while the answer went on saying `Europe/Zurich`.
    """
    return moment.replace(tzinfo=zone) if moment.tzinfo is None else moment
