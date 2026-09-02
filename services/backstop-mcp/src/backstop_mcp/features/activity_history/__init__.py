"""HTML-to-gist conversion, per-stream fetch, and per-stream grouping, for activity history.

`extract_gist_from_html`/`Gist`: convert HTML to Markdown with `markdownify`, squeeze its own
conversion artifacts (synthetic empty-header table rows, blank-line runs), and truncate at a
word boundary to a caller-supplied budget.

`GetActivityHistoryQuery`: per-stream single-page fetch plus grouping for `get_activity_history`.
Grouping is private on that query. See `queries/get_activity_history_query.py` for the
Backstop quirks this layer absorbs.

`ActivityRecordResponse`/`EmailRecordResponse`/`TimelineRecord`: the wire shape of one
history row, mapped from attributes. `ActivityHistoryResolvedResponse`/
`GetActivityHistoryResponse`: the top-level tool response union. See `responses.py`.

`GetActivityDetailQuery`: the `get_activity_detail` fetch — one activity's full
`entity-activity-details` record plus, for a meeting-or-calls handle, timings and attendees.
`ResourceIdentifierDto.from_activity_id` accepts a history composite
`{resource_type}_{resource_id}` or a search_activities row id and rejects a history email
handle (`email_*` / `emails_*` — those are `/emails` ids);
`ResourceIdentifierDto.is_meeting_or_call` gates the two `/meeting-or-calls` fetches for a
composite. A search id waits on the detail record's `type`. See
`queries/get_activity_detail_query.py`. `ActivityDetailResponse`/`AttendeeResponse`: that
tool's wire shape and the pure conversion into it. See `responses.py`.

`SearchActivitiesQuery`: `POST /entity-activities` pageNum loop for `search_activities`.
`EntityActivityType`: search-path stream names shared by the tool and the query.
`aggregate_entity_activities`: counts grouped by type, tag, party, or period.

`ActivityHistorySettings`: the per-stream page size and gist truncation budget, translated from
`config.ActivityHistoryConfig` by `get_activity_history_settings`. See `settings.py`.

The MCP tools live in `features/activity_history/tools/`.
"""

from backstop_mcp.features.activity_history.activity_type import (
    ActivityType,
    BackstopActivityType,
    Segment,
)
from backstop_mcp.features.activity_history.aggregate_entity_activities import (
    ActivityAggregateBy,
    aggregate_entity_activities,
)
from backstop_mcp.features.activity_history.api_responses import (
    ActivityAttributes,
    EmailAttributes,
)
from backstop_mcp.features.activity_history.dependencies import (
    get_activity_detail_query_factory,
    get_activity_history_query_factory,
    get_activity_history_settings,
    get_search_activities_query_factory,
)
from backstop_mcp.features.activity_history.entity_activity_type import (
    ENTITY_ACTIVITY_TYPES,
    EntityActivityType,
)
from backstop_mcp.features.activity_history.extract_gist_from_html import (
    Gist,
    extract_gist_from_html,
)
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
    EntityActivitiesFetchDto,
    EntityActivityDto,
    MeetingSpecificsDto,
    ResourceIdentifierDto,
)
from backstop_mcp.features.activity_history.queries import (
    MAX_RETRIEVABLE,
    GetActivityDetailQuery,
    GetActivityHistoryQuery,
    SearchActivitiesQuery,
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
    GetSearchActivitiesResponse,
    ResolvedPartyAsOfResponse,
    SearchActivitiesResolvedResponse,
    SearchActivitiesRowResponse,
    SearchActivitiesUnavailableResponse,
    TimelineRecord,
)
from backstop_mcp.features.activity_history.settings import ActivityHistorySettings
from backstop_mcp.features.collection_scan import (
    AggregateBucketDto,
    ScanCoverageResponse,
)

__all__ = [
    "ActivityAggregateBy",
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
    "AggregateBucketDto",
    "AttendeeChipDto",
    "AttendeeDto",
    "AttendeeResponse",
    "BackstopActivityType",
    "DateRangeResponse",
    "EmailAttributes",
    "EmailItemDto",
    "EmailPageDto",
    "EmailRecordResponse",
    "ENTITY_ACTIVITY_TYPES",
    "EntityActivitiesFetchDto",
    "EntityActivityDto",
    "EntityActivityType",
    "GetActivityDetailQuery",
    "GetActivityHistoryQuery",
    "GetActivityHistoryResponse",
    "GetSearchActivitiesResponse",
    "Gist",
    "MAX_RETRIEVABLE",
    "MeetingSpecificsDto",
    "ResolvedPartyAsOfResponse",
    "ResourceIdentifierDto",
    "ScanCoverageResponse",
    "SearchActivitiesQuery",
    "SearchActivitiesResolvedResponse",
    "SearchActivitiesRowResponse",
    "SearchActivitiesUnavailableResponse",
    "Segment",
    "TimelineRecord",
    "aggregate_entity_activities",
    "extract_gist_from_html",
    "get_activity_detail_query_factory",
    "get_activity_history_query_factory",
    "get_activity_history_settings",
    "get_search_activities_query_factory",
]
