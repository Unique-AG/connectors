"""Per-stream grouping: one fetched page's date_range and next continuation.

`group_activity_page` is a pure helper over already-fetched items. It does not re-sort —
Backstop already returns each stream newest-first (`-effectiveDate` / `-sentTimestamp`).
`date_range` is this page's min/max `occurred_at`, not a cumulative span. `next` is the params
to fetch that stream's next page, or `None` once the stream is exhausted.
"""

from collections.abc import Sequence
from datetime import UTC, date

from backstop_mcp.features.activity_history.fetch_activities_page import (
    ActivityType,
)
from backstop_mcp.features.activity_history.internal_dto import (
    ActivityItemDto,
    EmailItemDto,
)
from backstop_mcp.features.activity_history.responses import (
    ActivityContinuationResponse,
    ActivityGroupResponse,
    DateRangeResponse,
)

__all__ = ["group_activity_page"]


def _occurred_date(item: ActivityItemDto | EmailItemDto) -> date | None:
    if isinstance(item, EmailItemDto):
        sent = item.sent_timestamp
        if sent is None:
            return None
        utc = sent.astimezone(UTC) if sent.tzinfo is not None else sent.replace(tzinfo=UTC)
        return utc.date()
    return item.effective_date


def _date_range(items: Sequence[ActivityItemDto | EmailItemDto]) -> DateRangeResponse | None:
    dates = [occurred for item in items if (occurred := _occurred_date(item)) is not None]
    if not dates:
        return None
    return DateRangeResponse(start=min(dates), end=max(dates))


def group_activity_page(
    items: Sequence[ActivityItemDto | EmailItemDto],
    *,
    activity_type: ActivityType,
    end_of_stream: bool,
    limit: int,
    offset: int,
    since: date | None = None,
    until: date | None = None,
) -> ActivityGroupResponse[ActivityItemDto | EmailItemDto]:
    """Pass items through in fetch order; attach this page's date_range and next."""
    grouped = tuple(items)
    return ActivityGroupResponse(
        activity_type=activity_type,
        items=grouped,
        date_range=_date_range(grouped),
        next=(
            None
            if end_of_stream
            else ActivityContinuationResponse(
                limit=limit,
                offset=offset + len(grouped),
                since=since,
                until=until,
            )
        ),
    )
