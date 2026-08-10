"""The k-way merge across activity/email streams: one deterministic, stateless page at a time.

Each stream's position is a single integer, `consumed[s]` — how many of its records have
already been emitted. Backstop rejects an unaligned `page[offset]`, so that integer is turned
into a legal request per page:

    offset = (consumed[s] // limit) * limit      # always a multiple of limit
    skip   = consumed[s] %  limit                # dropped client-side from the fetched page

`fetch_offsets` computes the `offset` half of that pair for every active stream — this is what a
later, HTTP-aware layer calls *before* fetching, to know what `page[offset]` to send per stream
(via `fetch_activity_page`/`fetch_email_page`). Once that layer has fetched every active stream at
its aligned offset, `merge_page` takes the raw `(items, end_of_stream)` pages it got back, drops
each stream's first `skip` records, and buffers the rest. Merge-sort all buffers by
`(occurred_at desc, stream asc, id desc)`, take the first `limit`, and advance `consumed[s]` by
however many of that stream's records landed in the taken slice. A stream is exhausted — omitted
from the returned `consumed` mapping entirely — once its aligned page came back short (the backend
said so) *and* its whole buffered tail was consumed into the taken slice this round.

This is fully stateless: every page re-derives its buffers from the `consumed` integers alone, so
no record is dropped or repeated across pages. The cost is that a partially-consumed page is
re-fetched on the next call — a page that would have been requested anyway.

This module knows nothing about `BackstopClient`, HTTP, or segments, and does no fetching itself:
`merge_page` is a pure, synchronous function over pages a later, HTTP-aware layer already fetched.
Per the design doc's error-handling policy, a partial upstream failure (one active stream's fetch
errors while others succeed) fails the whole call — that layer is responsible for ensuring every
active stream's fetch succeeded before `merge_page` is ever called; this module doesn't tolerate a
missing or partial `pages` entry for an active stream.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, time
from functools import cmp_to_key
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from backstop_mcp.features.activity_history.streams import ActivityItem, EmailItem, StreamKind

__all__ = ["MergeResult", "MergedRecord", "fetch_offsets", "merge_page"]


class MergedRecord(BaseModel):
    """One item, tagged with the stream it came from and its normalized sort key.

    `occurred_at` is always a tz-aware UTC `datetime`, even for activities (date-only on the
    wire) — see `_occurred_at`. This is the minimal shape a later response-model layer needs to
    build a wire record; it deliberately doesn't duplicate `item.id` or anything else already
    reachable off `item`.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    stream: StreamKind
    item: ActivityItem | EmailItem
    occurred_at: datetime


class MergeResult(BaseModel):
    """One merged page: the records taken, and the `consumed` mapping for the next page.

    `consumed` omits any stream that reached full exhaustion this round — an absent stream is
    done, not "at offset 0" (see module docstring).
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    records: tuple[MergedRecord, ...]
    consumed: Mapping[StreamKind, int]


def _offset_and_skip(start: int, *, limit: int) -> tuple[int, int]:
    """The aligned `page[offset]` to request, and how many leading records to drop client-side.

    Shared by `fetch_offsets` (which only needs the `offset` half, before any fetch happens) and
    `merge_page` (which needs both, once the page requested at that `offset` is in hand) so the
    arithmetic lives in exactly one place.
    """
    return (start // limit) * limit, start % limit


def fetch_offsets(
    streams: Iterable[StreamKind], consumed: Mapping[StreamKind, int], *, limit: int
) -> dict[StreamKind, int]:
    """The aligned `page[offset]` a caller should request for each stream, given its progress.

    `consumed` gives each stream's progress (0 for a stream absent from it — the first-page
    case). Called by a later, HTTP-aware layer *before* fetching, so it knows what `offset` to
    pass to `fetch_activity_page`/`fetch_email_page` per stream; `merge_page` re-derives the same
    `offset` (and the `skip` half of the pair) once those fetches are back.
    """
    return {
        stream: _offset_and_skip(consumed.get(stream, 0), limit=limit)[0] for stream in streams
    }


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


def _compare(left: MergedRecord, right: MergedRecord) -> int:
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
    pages: Mapping[StreamKind, tuple[Sequence[ActivityItem] | Sequence[EmailItem], bool]],
    consumed: Mapping[StreamKind, int],
    *,
    limit: int,
) -> MergeResult:
    """Merge one already-fetched page from every active stream into the merged slice.

    `pages[stream]` is `(items, end_of_stream)` — exactly what `fetch_activity_page`/
    `fetch_email_page` produces for that stream at the `offset` `fetch_offsets` reported for it.
    `pages` is assumed to contain an entry for every currently active stream: per the design
    doc's error-handling policy, a partial upstream failure fails the whole call, so ensuring
    every active stream's fetch succeeded before calling this function is the caller's job, not
    something this pure function tolerates or papers over.

    `consumed` gives each stream's progress (0 for a stream absent from it — the first-page
    case), and is used both to compute the `skip` dropped from each fetched page and as the base
    for the returned `consumed[s] + taken_count`. Neither mapping argument is mutated.
    """
    stream_keys = tuple(pages.keys())
    starts = {stream: consumed.get(stream, 0) for stream in stream_keys}

    buffers: dict[StreamKind, list[MergedRecord]] = {}
    end_of_stream: dict[StreamKind, bool] = {}
    for stream in stream_keys:
        items, stream_end_of_stream = pages[stream]
        assert len(items) <= limit, (
            f"fetched page contract violated: stream {stream!r} has {len(items)} items, more "
            f"than the requested limit {limit}"
        )
        _offset, skip = _offset_and_skip(starts[stream], limit=limit)
        buffers[stream] = [
            MergedRecord(stream=stream, item=item, occurred_at=_occurred_at(item))
            for item in items[skip:]
        ]
        end_of_stream[stream] = stream_end_of_stream

    ordered = sorted(
        (record for records in buffers.values() for record in records),
        key=cmp_to_key(_compare),
    )
    taken = tuple(ordered[:limit])
    taken_counts = Counter(record.stream for record in taken)

    new_consumed: dict[StreamKind, int] = {}
    for stream in stream_keys:
        taken_count = taken_counts.get(stream, 0)
        buffered_count = len(buffers[stream])
        new_count = starts[stream] + taken_count
        if end_of_stream[stream] and taken_count == buffered_count:
            continue  # fully drained this round: omitted, not carried forward at 0
        new_consumed[stream] = new_count

    return MergeResult(records=taken, consumed=new_consumed)
