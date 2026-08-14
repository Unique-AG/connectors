"""Per-stream grouping: one fetched page's date_range and next continuation.

`group_page` is a pure helper over already-fetched items. It does not re-sort — Backstop
already returns each stream newest-first (`-effectiveDate` / `-sentTimestamp`). `date_range`
is this page's min/max `occurred_at`, not a cumulative span. `next` is the params to fetch
that stream's next page, or `None` once the stream is exhausted.
"""

from collections.abc import Sequence
from datetime import UTC, date

from backstop_mcp.features.activity_history.fetch_activities import (
    ActivityItem,
    ActivityType,
    EmailItem,
)
from backstop_mcp.features.activity_history.models import (
    ActivityContinuation,
    ActivityGroup,
    DateRange,
)

__all__ = ["group_page"]


def _occurred_date(item: ActivityItem | EmailItem) -> date | None:
    if isinstance(item, EmailItem):
        sent = item.sent_timestamp
        if sent is None:
            return None
        utc = sent.astimezone(UTC) if sent.tzinfo is not None else sent.replace(tzinfo=UTC)
        return utc.date()
    return item.effective_date


def _date_range(items: Sequence[ActivityItem | EmailItem]) -> DateRange | None:
    dates = [occurred for item in items if (occurred := _occurred_date(item)) is not None]
    if not dates:
        return None
    return DateRange(start=min(dates), end=max(dates))


def group_page(
    items: Sequence[ActivityItem | EmailItem],
    *,
    activity_type: ActivityType,
    end_of_stream: bool,
    limit: int,
    offset: int,
    since: date | None = None,
    until: date | None = None,
) -> ActivityGroup[ActivityItem | EmailItem]:
    """Pass items through in fetch order; attach this page's date_range and next."""
    grouped = tuple(items)
    return ActivityGroup(
        activity_type=activity_type,
        items=grouped,
        date_range=_date_range(grouped),
        next=(
            None
            if end_of_stream
            else ActivityContinuation(
                limit=limit,
                offset=offset + len(grouped),
                since=since,
                until=until,
            )
        ),
    )
