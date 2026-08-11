"""HTML-to-gist conversion, per-stream fetch, and the k-way merge/cursor, for activity history.

`to_gist`/`Gist`: convert HTML to Markdown with `markdownify`, squeeze its own conversion
artifacts (synthetic empty-header table rows, blank-line runs), and truncate at a word boundary
to a caller-supplied budget.

`fetch_activity_page`/`fetch_email_page`: the per-stream single-page fetch primitive behind
activity history — one HTTP call per (stream kind, entity, page), returning typed items
(`ActivityItem`/`EmailItem`) plus whether that stream is now exhausted. See
`fetch_activities.py`'s module docstring for the wire details (the two incompatible date
dialects, why pagination never follows `links.next`, why meetings/calls need one request per
type).

`merge_page`: the stateless k-way merge across streams — a pure, synchronous function that merges
already-fetched pages into a deterministically-ordered result plus the updated `consumed`
mapping. Fetching itself (HTTP, concurrency, `BackstopClient`) is a later, HTTP-aware layer's
job. See `merge.py`'s module docstring for the exact sort key; `consumed[s]` is itself the next
`page[offset]` for that stream.

`encode_cursor`/`decode_cursor`: the self-contained pagination cursor built on top of
`consumed` — a pydantic model serialized directly as a named JSON object, base64url-encoded,
carrying the full query state so the next page needs only the cursor string. See `cursor.py`'s
module docstring for the wire payload.

Response/wire models for a tool payload, config-driven page sizing, and any MCP tool surface all
live in later `activity_history` modules.
"""

from backstop_mcp.features.activity_history.cursor import (
    ActivityCursor,
    InvalidCursor,
    decode_cursor,
    encode_cursor,
)
from backstop_mcp.features.activity_history.fetch_activities import (
    ActivityItem,
    ActivityPage,
    ActivityType,
    BackstopActivityType,
    EmailItem,
    EmailPage,
    Segment,
    fetch_activity_page,
    fetch_email_page,
)
from backstop_mcp.features.activity_history.gist import Gist, to_gist
from backstop_mcp.features.activity_history.merge import (
    ActivityWithType,
    UnifiedActivities,
    merge_page,
)

__all__ = [
    "ActivityCursor",
    "ActivityItem",
    "ActivityPage",
    "ActivityType",
    "ActivityWithType",
    "BackstopActivityType",
    "EmailItem",
    "EmailPage",
    "Gist",
    "InvalidCursor",
    "Segment",
    "UnifiedActivities",
    "decode_cursor",
    "encode_cursor",
    "fetch_activity_page",
    "fetch_email_page",
    "merge_page",
    "to_gist",
]
