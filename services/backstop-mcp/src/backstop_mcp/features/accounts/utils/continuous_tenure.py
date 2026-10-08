"""How long an owner has held without a break, from account spans — closed accounts included.

An owner's tenure is not any one account's start date: private banks, platforms and nominee
structures open a fresh account per mandate and close the old one, so the oldest open account can
be years younger than the relationship. Spans that overlap or touch (closed on the 31st, next
opened on the 1st) are one run; a gap of more than a day ends it.
"""

from collections.abc import Iterable
from datetime import date, timedelta

from backstop_mcp.features.accounts.internal_dto import AccountSpanDto, TenureDto

_TOUCHING = timedelta(days=1)


def continuous_tenure(spans: Iterable[AccountSpanDto], *, today: date) -> TenureDto:
    """The start of the run that reaches `today`, or `None` when the owner is not held through it.

    An open span runs through `today`; so does one closed on or after `today`. A span with no
    start, or closed with no closed date, cannot be placed and is counted in `undated_accounts`.
    """
    collected = tuple(spans)
    placed = sorted(placed_span for span in collected if (placed_span := _placed(span)))
    run: tuple[date, date] | None = None
    for start, end in placed:
        # `start - 1 day`, not `end + 1 day`: an open run ends on `date.max`, which cannot grow.
        if run is not None and start - _TOUCHING <= run[1]:
            run = (run[0], max(run[1], end))
        else:
            run = (start, end)
    return TenureDto(
        continuous_since=run[0] if run is not None and run[1] >= today else None,
        undated_accounts=len(collected) - len(placed),
    )


def _placed(span: AccountSpanDto) -> tuple[date, date] | None:
    """`(start, end)` on the timeline, `date.max` for open; `None` when it cannot be placed."""
    if span.start is None:
        return None
    if span.is_open:
        return (span.start, date.max)
    if span.end is None:
        return None
    return (span.start, span.end)
