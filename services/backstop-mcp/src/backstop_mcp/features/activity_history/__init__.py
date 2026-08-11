"""HTML-to-gist conversion, per-stream fetch, and the k-way merge/cursor, for activity history.

`to_gist`/`Gist`: convert HTML to Markdown with `markdownify`, squeeze its own conversion
artifacts (synthetic empty-header table rows, blank-line runs), and truncate at a word boundary
to a caller-supplied budget.

`fetch_activity_page`/`fetch_email_page`: the per-stream single-page fetch primitive behind
activity history — one HTTP call per (stream kind, entity, page), returning typed items
(`ActivityItem`/`EmailItem`) plus whether that stream is now exhausted. See
`fetch_activities.py`'s module docstring for the Backstop quirks this layer absorbs.

`merge_page`: merges already-fetched pages into a deterministically-ordered result plus the
updated `consumed` map (`consumed[s]` is the next `page[offset]` for that stream). See
`merge.py`.

`encode_cursor`/`decode_cursor`: self-contained pagination cursor carrying the full query state
so the next page needs only the cursor string. See `cursor.py`.

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
from backstop_mcp.features.activity_history.gist_from_html import Gist, to_gist
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
