"""Merge already-fetched activity/email pages into one ordered result.

`consumed[s]` is how many records stream `s` has already emitted, and is itself the next
`page[offset]` for that stream (or the stream is absent once exhausted). `merge_page` drains
every fetched page fully, sorts by `(occurred_at desc, stream asc, id desc)`, and returns the
updated `consumed` map — short pages are dropped from it.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, time
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from backstop_mcp.features.activity_history.fetch_activities import (
    ActivityItem,
    ActivityType,
    EmailItem,
)

__all__ = ["ActivityWithType", "UnifiedActivities", "merge_page"]

_OLDEST = datetime.min.replace(tzinfo=UTC)


class ActivityWithType(BaseModel):
    """One merged item with its stream and normalized sort timestamp."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    stream: ActivityType
    item: ActivityItem | EmailItem
    occurred_at: datetime


class UnifiedActivities(BaseModel):
    """Merged records plus `consumed` for the next page (exhausted streams omitted)."""

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    records: tuple[ActivityWithType, ...]
    consumed: Mapping[ActivityType, int]


def _occurred_at(item: ActivityItem | EmailItem) -> datetime:
    """UTC sort key: email timestamp, or midnight UTC of an activity's date."""
    if isinstance(item, EmailItem):
        sent = item.sent_timestamp
        if sent is None:
            return _OLDEST
        return sent.astimezone(UTC) if sent.tzinfo is not None else sent.replace(tzinfo=UTC)
    if item.effective_date is None:
        return _OLDEST
    return datetime.combine(item.effective_date, time.min, tzinfo=UTC)


def merge_page(
    pages: Mapping[ActivityType, tuple[Sequence[ActivityItem] | Sequence[EmailItem], bool]],
    consumed: Mapping[ActivityType, int],
) -> UnifiedActivities:
    """Merge every item from every page; advance `consumed` by each full page (drop if short)."""
    records: list[ActivityWithType] = []
    new_consumed: dict[ActivityType, int] = {}
    for stream, (items, end_of_stream) in pages.items():
        records.extend(
            ActivityWithType(stream=stream, item=item, occurred_at=_occurred_at(item))
            for item in items
        )
        if not end_of_stream:
            new_consumed[stream] = consumed.get(stream, 0) + len(items)

    # Stable multi-pass for (occurred_at desc, stream asc, id desc).
    records.sort(key=lambda r: r.item.id, reverse=True)
    records.sort(key=lambda r: r.stream)
    records.sort(key=lambda r: r.occurred_at, reverse=True)
    return UnifiedActivities(records=tuple(records), consumed=new_consumed)
