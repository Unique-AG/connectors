"""HTML-to-gist conversion, per-stream fetch, and per-stream grouping, for activity history.

`extract_gist_from_html`/`Gist`: convert HTML to Markdown with `markdownify`, squeeze its own
conversion artifacts (synthetic empty-header table rows, blank-line runs), and truncate at a
word boundary to a caller-supplied budget.

`fetch_activity_page`/`fetch_email_page`/`fetch_activities_page`: the per-stream single-page
fetch primitive behind activity history — one HTTP call per (activity type, entity, page),
returning typed items (`ActivityItemDto`/`EmailItemDto`) plus whether that type is now exhausted.
`fetch_activities_page` dispatches email vs activity. See `fetch_activities_page.py`'s module
docstring for the Backstop quirks this layer absorbs.

`group_activity_page`: computes one stream page's `date_range` (min/max `occurred_at` among this
page's items) and `next` continuation (`None` once that stream is exhausted). Items pass through
in fetch order — no client-side re-sort. See `group_activity_page.py`.

`ActivityRecordResponse`/`EmailRecordResponse`/`TimelineRecord`/`to_timeline_record`: the wire
shape of one fetched item and the union conversion into it. `ActivityHistoryResolvedResponse`/
`GetActivityHistoryResponse`: the top-level tool response union. See `responses.py`.

`fetch_activity_detail`/`fetch_meeting_specifics`/`fetch_attendees`: the `get_activity_detail`
fetch primitive — one activity's full `entity-activity-details` record plus, for a
meeting-or-calls handle, timings and attendees. `ResourceIdentifierDto.from_activity_id` splits
the timeline `activity_id` into `{resource_type, resource_id}`;
`ResourceIdentifierDto.is_meeting_or_call` gates the two `/meeting-or-calls` fetches. See
`fetch_activity_detail.py`.
`ActivityDetailResponse`/`AttendeeResponse`: that tool's wire shape
and the pure conversion into it. See `responses.py`.

`ActivityHistorySettings`: the per-stream page size and gist truncation budget, translated from
`config.ActivityHistoryConfig` by `get_activity_history_settings`. See `settings.py`.

The MCP tools live in `features/activity_history/tools/`.
"""

from backstop_mcp.features.activity_history.api_responses import ActivityAttributes
from backstop_mcp.features.activity_history.dependencies import get_activity_history_settings
from backstop_mcp.features.activity_history.extract_gist_from_html import (
    Gist,
    extract_gist_from_html,
)
from backstop_mcp.features.activity_history.fetch_activities_page import (
    ActivityType,
    BackstopActivityType,
    Segment,
    fetch_activities_page,
    fetch_activity_page,
    fetch_email_page,
)
from backstop_mcp.features.activity_history.fetch_activity_detail import (
    fetch_activity_detail,
    fetch_attendees,
    fetch_meeting_specifics,
)
from backstop_mcp.features.activity_history.group_activity_page import group_activity_page
from backstop_mcp.features.activity_history.internal_dto import (
    ActivityDetailDto,
    ActivityItemDto,
    ActivityPageDto,
    ActivityRegardingDto,
    ActivityTagChipDto,
    AttendeeChipDto,
    AttendeeDto,
    EmailItemDto,
    EmailPageDto,
    MeetingSpecificsDto,
    ResourceIdentifierDto,
)
from backstop_mcp.features.activity_history.responses import (
    ActivityContinuationResponse,
    ActivityDetailResponse,
    ActivityGroupResponse,
    ActivityHistoryResolvedResponse,
    ActivityRecordResponse,
    ActivityRegardingResponse,
    ActivityTagChipResponse,
    AttendeeResponse,
    DateRangeResponse,
    EmailRecordResponse,
    GetActivityHistoryResponse,
    ResolvedPartyAsOfResponse,
    TimelineRecord,
    to_timeline_record,
)
from backstop_mcp.features.activity_history.settings import ActivityHistorySettings

__all__ = [
    "ActivityAttributes",
    "ActivityContinuationResponse",
    "ActivityDetailDto",
    "ActivityDetailResponse",
    "ActivityGroupResponse",
    "ActivityHistoryResolvedResponse",
    "ActivityHistorySettings",
    "ActivityItemDto",
    "ActivityPageDto",
    "ActivityRecordResponse",
    "ActivityRegardingDto",
    "ActivityRegardingResponse",
    "ActivityTagChipDto",
    "ActivityTagChipResponse",
    "ActivityType",
    "AttendeeChipDto",
    "AttendeeDto",
    "AttendeeResponse",
    "BackstopActivityType",
    "DateRangeResponse",
    "EmailItemDto",
    "EmailPageDto",
    "EmailRecordResponse",
    "GetActivityHistoryResponse",
    "Gist",
    "MeetingSpecificsDto",
    "ResolvedPartyAsOfResponse",
    "ResourceIdentifierDto",
    "Segment",
    "TimelineRecord",
    "extract_gist_from_html",
    "fetch_activity_detail",
    "fetch_activity_page",
    "fetch_activities_page",
    "fetch_attendees",
    "fetch_email_page",
    "fetch_meeting_specifics",
    "get_activity_history_settings",
    "group_activity_page",
    "to_timeline_record",
]
