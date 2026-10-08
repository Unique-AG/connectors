"""An owner's unbroken holding through today, merged across its accounts, closed ones included."""

from collections.abc import Iterable
from datetime import date, timedelta

from backstop_mcp.features.accounts.internal_dto import AccountSpanDto, TenureDto

_TOUCHING = timedelta(days=1)


def continuous_tenure(spans: Iterable[AccountSpanDto], *, today: date) -> TenureDto:
    """The start of the run of touching or overlapping spans that covers `today`, else `None`.

    Spans starting after `today` are not held yet and are ignored. A span with no start, or
    closed with no closed date, is counted in `undated_accounts`.
    """
    collected = tuple(spans)
    placed = sorted(placed_span for span in collected if (placed_span := _placed(span)))
    run: tuple[date, date] | None = None
    for start, end in placed:
        if start > today:
            continue
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
