"""HTML-to-gist conversion, plus per-stream fetch, for meeting notes and other activity history.

`to_gist`/`Gist`: convert HTML to Markdown with `markdownify`, squeeze its own conversion
artifacts (synthetic empty-header table rows, blank-line runs), and truncate at a word boundary
to a caller-supplied budget.

`fetch_activity_page`/`fetch_email_page`: the per-stream single-page fetch primitive behind
activity history — one HTTP call per (stream kind, party, page), returning typed items
(`ActivityItem`/`EmailItem`) plus whether that stream is now exhausted. See `streams.py`'s module
docstring for the wire details (the two incompatible date dialects, why pagination never follows
`links.next`, why meetings/calls need one request per type).

The k-way merge across streams, the cursor, config-driven page sizing, and any MCP tool surface
all live in later `activity_history` modules.
"""

from backstop_mcp.features.activity_history.gist import Gist, to_gist
from backstop_mcp.features.activity_history.streams import (
    ActivityItem,
    ActivityPage,
    ActivityStreamKind,
    EmailItem,
    EmailPage,
    PartySegment,
    StreamKind,
    fetch_activity_page,
    fetch_email_page,
)

__all__ = [
    "ActivityItem",
    "ActivityPage",
    "ActivityStreamKind",
    "EmailItem",
    "EmailPage",
    "Gist",
    "PartySegment",
    "StreamKind",
    "fetch_activity_page",
    "fetch_email_page",
    "to_gist",
]
