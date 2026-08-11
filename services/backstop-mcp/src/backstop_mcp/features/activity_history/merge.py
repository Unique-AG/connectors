"""The k-way merge across activity/email streams: one deterministic, stateless page at a time.

Each stream's position is a single integer, `consumed[s]` — how many of its records have
already been emitted. Because `merge_page` always drains every fetched page fully,
`consumed[s]` is itself a legal `page[offset]` for the next fetch (or the stream is gone) — a
later, HTTP-aware layer passes it straight through to `fetch_activity_page`/`fetch_email_page`.

Once that layer has fetched every active stream at its `consumed` offset, `merge_page` takes the
raw `(items, end_of_stream)` pages it got back, merge-sorts every item by
`(occurred_at desc, stream asc, id desc)`, and advances `consumed[s]` by however many of that
stream's records were in the merged result (all of them — this function does not truncate). A
stream is exhausted — omitted from the returned `consumed` mapping entirely — once its page came
back short (the backend said so).

This is fully stateless: every page re-derives its buffers from the `consumed` integers alone, so
no record is dropped or repeated across pages.

This module knows nothing about `BackstopClient`, HTTP, or segments, and does no fetching itself:
`merge_page` is a pure, synchronous function over pages a later, HTTP-aware layer already fetched.
Per the design doc's error-handling policy, a partial upstream failure (one active stream's fetch
errors while others succeed) fails the whole call — that layer is responsible for ensuring every
active stream's fetch succeeded before `merge_page` is ever called; this module doesn't tolerate a
missing or partial `pages` entry for an active stream.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, time
from functools import cmp_to_key
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from backstop_mcp.features.activity_history.fetch_activities import (
    ActivityItem,
    ActivityType,
    EmailItem,
)

__all__ = ["ActivityWithType", "UnifiedActivities", "merge_page"]


class ActivityWithType(BaseModel):
    """One item, tagged with the stream it came from and its normalized sort key.

    `occurred_at` is always a tz-aware UTC `datetime`, even for activities (date-only on the
    wire) — see `_occurred_at`. This is the minimal shape a later response-model layer needs to
    build a wire record; it deliberately doesn't duplicate `item.id` or anything else already
    reachable off `item`.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    stream: ActivityType
    item: ActivityItem | EmailItem
    occurred_at: datetime


class UnifiedActivities(BaseModel):
    """One merged page: every record from the fetched pages, and `consumed` for the next page.

    `consumed` omits any stream that reached full exhaustion this round — an absent stream is
    done, not "at offset 0" (see module docstring).
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    records: tuple[ActivityWithType, ...]
    consumed: Mapping[ActivityType, int]


def _occurred_at(item: ActivityItem | EmailItem) -> datetime:
    """Normalize an item's own timestamp to a tz-aware UTC comparison key.

    Activities carry only a date (`effective_date`); it is treated as midnight UTC of that day,
    which is what makes a same-day email — a real timestamp, almost never exactly midnight —
    sort above a same-day meeting. Emails carry a real `sent_timestamp`, normalized to UTC (a
    naive value, which shouldn't occur on the wire but is handled defensively, is assumed
    already UTC rather than raising). A missing timestamp sorts as the oldest possible record
    rather than raising, since ordering — not filtering — is this module's job.
    """
    if isinstance(item, EmailItem):
        sent = item.sent_timestamp
        if sent is None:
            return datetime.min.replace(tzinfo=UTC)
        return sent.astimezone(UTC) if sent.tzinfo is not None else sent.replace(tzinfo=UTC)
    if item.effective_date is None:
        return datetime.min.replace(tzinfo=UTC)
    return datetime.combine(item.effective_date, time.min, tzinfo=UTC)


def _compare(left: ActivityWithType, right: ActivityWithType) -> int:
    """`(occurred_at desc, stream asc, id desc)` — a full total order, no ties possible.

    Only `occurred_at` and `id` carry a `desc` marker in the design; `stream` has none, meaning
    ascending. Getting this backwards on any one of the three corrupts every downstream answer,
    so each branch is spelled out rather than folded into a single tuple-key comparison.

    The design doc calls this field "resource_id"; here it is `item.id` (the JSON:API resource
    id) deliberately — `EmailItem` has no `resource_id` field at all (only `ActivityItem` does,
    and it can be `None`), so `item.id` is the only field that produces a total order across both
    item kinds. This is a reinterpretation of the design doc's language, not an oversight.
    """
    if left.occurred_at != right.occurred_at:
        return -1 if left.occurred_at > right.occurred_at else 1
    if left.stream != right.stream:
        return -1 if left.stream < right.stream else 1
    if left.item.id != right.item.id:
        return -1 if left.item.id > right.item.id else 1
    return 0


def merge_page(
    pages: Mapping[ActivityType, tuple[Sequence[ActivityItem] | Sequence[EmailItem], bool]],
    consumed: Mapping[ActivityType, int],
) -> UnifiedActivities:
    """Merge every already-fetched page from every active stream into one ordered result.

    `pages[stream]` is `(items, end_of_stream)` — exactly what `fetch_activity_page`/
    `fetch_email_page` produces for that stream at `offset=consumed.get(stream, 0)`.
    `pages` is assumed to contain an entry for every currently active stream: per the design
    doc's error-handling policy, a partial upstream failure fails the whole call, so ensuring
    every active stream's fetch succeeded before calling this function is the caller's job, not
    something this pure function tolerates or papers over.

    `consumed` gives each stream's progress (0 for a stream absent from it — the first-page
    case) and is used as the base for the returned `consumed[s] + page_count`. Neither mapping
    argument is mutated. Every item from every page is included in the result — there is no
    merged-page size cap here.
    """
    stream_keys = tuple(pages.keys())
    starts = {stream: consumed.get(stream, 0) for stream in stream_keys}

    records: list[ActivityWithType] = []
    end_of_stream: dict[ActivityType, bool] = {}
    page_counts: dict[ActivityType, int] = {}
    for stream in stream_keys:
        items, stream_end_of_stream = pages[stream]
        page_counts[stream] = len(items)
        records.extend(
            ActivityWithType(stream=stream, item=item, occurred_at=_occurred_at(item))
            for item in items
        )
        end_of_stream[stream] = stream_end_of_stream

    ordered = tuple(sorted(records, key=cmp_to_key(_compare)))

    new_consumed: dict[ActivityType, int] = {}
    for stream in stream_keys:
        if end_of_stream[stream]:
            continue  # fully drained this round: omitted, not carried forward at 0
        new_consumed[stream] = starts[stream] + page_counts[stream]

    return UnifiedActivities(records=ordered, consumed=new_consumed)
