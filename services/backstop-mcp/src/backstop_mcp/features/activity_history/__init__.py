"""HTML-to-gist conversion, per-stream fetch, and the k-way merge/cursor, for activity history.

`to_gist`/`Gist`: convert HTML to Markdown with `markdownify`, squeeze its own conversion
artifacts (synthetic empty-header table rows, blank-line runs), and truncate at a word boundary
to a caller-supplied budget.

`fetch_activity_page`/`fetch_email_page`: the per-stream single-page fetch primitive behind
activity history — one HTTP call per (stream kind, entity, page), returning typed items
(`ActivityItem`/`EmailItem`) plus whether that stream is now exhausted. See `streams.py`'s module
docstring for the wire details (the two incompatible date dialects, why pagination never follows
`links.next`, why meetings/calls need one request per type).

`fetch_offsets`/`merge_page`: the stateless k-way merge across streams. `fetch_offsets` computes
the aligned `page[offset]` a caller should request per stream, given each stream's `consumed`
count; `merge_page` is a pure, synchronous function that merges the already-fetched pages back
into a deterministically-ordered slice plus the updated `consumed` mapping. Fetching itself
(HTTP, concurrency, `BackstopClient`) is a later, HTTP-aware layer's job. See `merge.py`'s module
docstring for the `consumed -> (offset, skip)` alignment and the exact sort key.

`encode_cursor`/`decode_and_validate_cursor`: the compact pagination cursor built on top of
`consumed` — a JSON-array wire payload validated by a pydantic `TypeAdapter`, base64url-encoded —
with digest-based detection of a stale/conflicting cursor. See `cursor.py`'s module docstring for
the wire payload and the conflict-vs-invalid error split.

Response/wire models for a tool payload, config-driven page sizing, and any MCP tool surface all
live in later `activity_history` modules.
"""

from backstop_mcp.features.activity_history.cursor import (
    CursorConflict,
    InvalidCursor,
    decode_and_validate_cursor,
    encode_cursor,
)
from backstop_mcp.features.activity_history.gist import Gist, to_gist
from backstop_mcp.features.activity_history.merge import (
    MergedRecord,
    MergeResult,
    fetch_offsets,
    merge_page,
)
from backstop_mcp.features.activity_history.streams import (
    ActivityItem,
    ActivityPage,
    ActivityStreamKind,
    EmailItem,
    EmailPage,
    Segment,
    StreamKind,
    fetch_activity_page,
    fetch_email_page,
)

__all__ = [
    "ActivityItem",
    "ActivityPage",
    "ActivityStreamKind",
    "CursorConflict",
    "EmailItem",
    "EmailPage",
    "Gist",
    "InvalidCursor",
    "MergeResult",
    "MergedRecord",
    "Segment",
    "StreamKind",
    "decode_and_validate_cursor",
    "encode_cursor",
    "fetch_activity_page",
    "fetch_email_page",
    "fetch_offsets",
    "merge_page",
    "to_gist",
]
