"""HTML-to-gist conversion, per-stream fetch, and per-stream grouping, for activity history.

`to_gist`/`Gist`: convert HTML to Markdown with `markdownify`, squeeze its own conversion
artifacts (synthetic empty-header table rows, blank-line runs), and truncate at a word boundary
to a caller-supplied budget.

`fetch_activity_page`/`fetch_email_page`/`fetch_activities_page_by_type`: the per-stream single-page
fetch primitive behind activity history — one HTTP call per (activity type, entity, page),
returning typed items (`ActivityItem`/`EmailItem`) plus whether that type is now exhausted.
`fetch_activities_page_by_type` dispatches email vs activity. See `fetch_activities.py`'s module
docstring for the Backstop quirks this layer absorbs.

`group_page`: computes one stream page's `date_range` (min/max `occurred_at` among this page's
items) and `next` continuation (`None` once that stream is exhausted). Items pass through in
fetch order — no client-side re-sort. See `group.py`.

`ActivityRecordResponse`/`EmailRecordResponse`/`TimelineRecord`/`to_timeline_record`: the wire
shape of one fetched item and the pure conversion into it. `ActivityHistoryResolvedResponse`/
`GetActivityHistoryResponse`: the top-level tool response union. See `responses.py`.

`fetch_activity_detail`/`fetch_meeting_specifics`/`fetch_attendees`: the `get_activity_detail`
fetch primitive — one activity's full `entity-activity-details` record plus, for a
meeting-or-calls handle, timings and attendees. `parse_activity_handle` splits the timeline
`activity_id` into `{resource_type, resource_id}`; `ActivityHandle.is_meeting_or_call` gates
the two `/meeting-or-calls` fetches. See `fetch_activity_detail.py` and `activity_handle.py`.
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
from backstop_mcp.features.activity_history.activity_handle import (
    ActivityHandle,
    parse_activity_handle,
)
from backstop_mcp.features.activity_history.fetch_activities import (
    ActivityItem,
    ActivityPage,
    ActivityType,
    BackstopActivityType,
    EmailItem,
    EmailPage,
    Segment,
    fetch_activities_page_by_type,
    fetch_activity_page,
    fetch_email_page,
)
from backstop_mcp.features.activity_history.fetch_activity_detail import (
    ActivityDetail,
    Attendee,
    MeetingSpecifics,
    fetch_activity_detail,
    fetch_attendees,
    fetch_meeting_specifics,
)
from backstop_mcp.features.activity_history.gist_from_html import Gist, to_gist
from backstop_mcp.features.activity_history.group import group_page
from backstop_mcp.features.activity_history.models import (
    ActivityContinuation,
    ActivityGroup,
    DateRange,
)
from backstop_mcp.features.activity_history.responses import (
    ActivityHistoryResolvedResponse,
    ActivityRecordResponse,
    EmailRecordResponse,
    GetActivityHistoryResponse,
    ResolvedPartyAsOfResponse,
    TimelineRecord,
    resolved_party_as_of_response,
    to_timeline_record,
)
from backstop_mcp.features.activity_history.settings import ActivityHistorySettings

__all__ = [
    "ActivityContinuation",
    "ActivityDetail",
    "ActivityDetailResponse",
    "ActivityGroup",
    "ActivityHandle",
    "ActivityHistoryResolvedResponse",
    "ActivityHistorySettings",
    "ActivityItem",
    "ActivityPage",
    "ActivityRecordResponse",
    "ActivityType",
    "Attendee",
    "AttendeeResponse",
    "BackstopActivityType",
    "DateRange",
    "EmailItem",
    "EmailPage",
    "EmailRecordResponse",
    "GetActivityHistoryResponse",
    "Gist",
    "MeetingSpecifics",
    "ResolvedPartyAsOfResponse",
    "Segment",
    "TimelineRecord",
    "fetch_activity_detail",
    "fetch_activity_page",
    "fetch_activities_page_by_type",
    "fetch_attendees",
    "fetch_email_page",
    "fetch_meeting_specifics",
    "group_page",
    "parse_activity_handle",
    "resolved_party_as_of_response",
    "to_activity_detail_response",
    "to_gist",
    "to_timeline_record",
]
