"""An owner's unbroken holding runs, merged across its accounts, closed ones included."""

from collections.abc import Iterable
from datetime import date, timedelta

from backstop_mcp.features.accounts.internal_dto import AccountSpanDto, TenureDto, TenureRunDto

_TOUCHING = timedelta(days=1)
_DAYS_PER_YEAR = 365.25


def tenure_runs(spans: Iterable[AccountSpanDto], *, today: date) -> TenureDto:
    """Every run of touching or overlapping spans, longest first, the more recent on a tie.

    A span starting after `today` is not held yet: it only extends a run it touches, as a booked
    rollover does, and never starts one. A span with no start, closed with no closed date, or
    closed before it started is counted in `undated_accounts`.
    """
    collected = tuple(spans)
    placed = sorted(placed_span for span in collected if (placed_span := _placed(span)))
    merged: list[tuple[date, date]] = []
    for start, end in placed:
        # `start - 1 day`, not `end + 1 day`: an open run ends on `date.max`, which cannot grow.
        if merged and start - _TOUCHING <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    started = [(start, end) for start, end in merged if start <= today]
    longest_first = sorted(
        started, key=lambda run: (_held_days(*run, today=today), run[0]), reverse=True
    )
    return TenureDto(
        runs=tuple(_run(start, end, today=today) for start, end in longest_first),
        undated_accounts=len(collected) - len(placed),
    )


def _placed(span: AccountSpanDto) -> tuple[date, date] | None:
    """`(start, end)` on the timeline, `date.max` for open; `None` when it cannot be placed."""
    if span.start is None:
        return None
    if span.is_open:
        return (span.start, date.max)
    if span.end is None or span.end < span.start:
        return None
    return (span.start, span.end)


def _held_days(start: date, end: date, *, today: date) -> int:
    """Days held so far: a run closing after `today` has only been held through `today`."""
    return (min(end, today) - start).days


def _run(start: date, end: date, *, today: date) -> TenureRunDto:
    return TenureRunDto(
        start=start,
        end=None if end == date.max else end,
        years=round(_held_days(start, end, today=today) / _DAYS_PER_YEAR, 2),
    )
