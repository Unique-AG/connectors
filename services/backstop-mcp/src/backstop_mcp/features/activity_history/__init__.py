"""HTML-to-gist conversion, per-stream fetch, and the k-way merge/cursor, for activity history.

`to_gist`/`Gist`: convert HTML to Markdown with `markdownify`, squeeze its own conversion
artifacts (synthetic empty-header table rows, blank-line runs), and truncate at a word boundary
to a caller-supplied budget.

`fetch_activity_page`/`fetch_email_page`/`fetch_activities_page_by_type`: the per-stream single-page
fetch primitive behind activity history — one HTTP call per (activity type, entity, page),
returning typed items (`ActivityItem`/`EmailItem`) plus whether that type is now exhausted.
`fetch_activities_page_by_type` dispatches email vs activity. See `fetch_activities.py`'s module
docstring for the Backstop quirks this layer absorbs.

`merge_page`: merges already-fetched pages into a deterministically-ordered result plus the
updated `consumed` map (`consumed[s]` is the next `page[offset]` for that stream). See
`merge.py`.

`encode_cursor`/`decode_cursor`: self-contained pagination cursor carrying the full query state
so the next page needs only the cursor string. See `cursor.py`.

`ActivityRecordResponse`/`EmailRecordResponse`/`TimelineRecord`/`to_timeline_record`: the wire
shape of one merged record and the pure conversion into it. `ActivityHistoryResolvedResponse`/
`GetActivityHistoryResponse`: the top-level tool response union. See `responses.py`.

`fetch_activity_detail`/`fetch_attendees`/`is_meeting_or_call`: the `get_activity_detail` fetch
primitive — one activity's full `entity-activity-details` record plus its (conditional)
attendees. See `fetch_activity_detail.py`'s module docstring for the wire field names guessed
there, not byte-verified against a live instance the way the rest of this feature was.
`ActivityDetailResponse`/`AttendeeResponse`/`to_activity_detail_response`: that tool's wire shape
and the pure conversion into it. See `activity_detail_responses.py`.

`ActivityHistorySettings`: the per-stream page size and gist truncation budget, translated from
`config.ActivityHistoryConfig` by `create_app`. See `settings.py`.

The MCP tool surface itself lives in a later `activity_history` module.
"""

from backstop_mcp.features.activity_history.activity_detail_responses import (
    ActivityDetailResponse,
    AttendeeResponse,
    to_activity_detail_response,
)
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
    fetch_activities_page_by_type,
    fetch_email_page,
)
from backstop_mcp.features.activity_history.fetch_activity_detail import (
    ActivityDetail,
    Attendee,
    fetch_activity_detail,
    fetch_attendees,
    is_meeting_or_call,
)
from backstop_mcp.features.activity_history.gist_from_html import Gist, to_gist
from backstop_mcp.features.activity_history.merge import (
    ActivityWithType,
    UnifiedActivities,
    merge_page,
)
from backstop_mcp.features.activity_history.responses import (
    ActivityHistoryResolvedResponse,
    ActivityRecordResponse,
    EmailRecordResponse,
    GetActivityHistoryResponse,
    TimelineRecord,
    to_timeline_record,
)
from backstop_mcp.features.activity_history.settings import ActivityHistorySettings

__all__ = [
    "ActivityCursor",
    "ActivityDetail",
    "ActivityDetailResponse",
    "ActivityHistoryResolvedResponse",
    "ActivityHistorySettings",
    "ActivityItem",
    "ActivityPage",
    "ActivityRecordResponse",
    "ActivityType",
    "ActivityWithType",
    "Attendee",
    "AttendeeResponse",
    "BackstopActivityType",
    "EmailItem",
    "EmailPage",
    "EmailRecordResponse",
    "GetActivityHistoryResponse",
    "Gist",
    "InvalidCursor",
    "Segment",
    "TimelineRecord",
    "UnifiedActivities",
    "decode_cursor",
    "encode_cursor",
    "fetch_activity_detail",
    "fetch_activity_page",
    "fetch_activities_page_by_type",
    "fetch_attendees",
    "fetch_email_page",
    "is_meeting_or_call",
    "merge_page",
    "to_activity_detail_response",
    "to_gist",
    "to_timeline_record",
]
