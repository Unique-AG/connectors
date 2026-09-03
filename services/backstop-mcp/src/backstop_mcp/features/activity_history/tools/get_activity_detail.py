"""`get_activity_detail`: full converted body, meeting specifics, and attendees for one activity.

`activity_id` is a complete, self-sufficient handle — no party resolution needed. A
`get_activity_history` composite `{resourceType}_{resourceId}` yields both the bare resource
id every detail endpoint wants and the resource type that says which endpoints apply (see
`ResourceIdentifierDto`). A `search_activities` row `activity_id` (same value as `id`) is
already that bare id (`/entity-activity-details/{id}` answers it live); meeting extras then
follow the detail record's `type`, because a search id has no resource type. A history
email handle is rejected: `/emails` ids (body via `contentUrl`) are not this id space.

The query gathers the three GETs for a meeting/call composite. A note or document composite
is one request: both `/meeting-or-calls` paths 404 for a resource id that is not a
meeting/call. A bare id fetches detail first, then the two meeting endpoints only when
`type` is meeting or call.

A stale or invented `activity_id` raises rather than returning a bespoke not-found response.
An empty handle fails locally as a `ToolError`; one that is well-formed but unknown becomes
a 404 `BackstopApiError` (`/entity-activity-details` answers 200 with null primary data for
those, which `BackstopApiResourceDocument.require_data` converts).
"""

import logging
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.activity_history import (
    ActivityDetailResponse,
    GetActivityDetailQuery,
    ResourceIdentifierDto,
)
from backstop_mcp.features.activity_history.dependencies import get_activity_detail_query_factory
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    output_schema=published_output_schema(ActivityDetailResponse),
)
async def get_activity_detail(
    ctx: Context,
    activity_id: Annotated[
        str,
        Field(
            description=(
                "The `activity_id` from get_activity_history (`meeting-or-calls_76537547`) or "
                "the `id` from a search_activities row (`1659094659`). Both resolve on "
                "`/entity-activity-details`. Do not pass a history email handle — those are "
                "`/emails` ids. Never invent or guess one — an unknown id raises rather than "
                "returning a not-found response."
            ),
        ),
    ],
    get_activity_detail_query: GetActivityDetailQuery = Depends(get_activity_detail_query_factory),
) -> ActivityDetailResponse:
    """Fetch one activity's full body, meeting specifics, attendees, and attachment list.

    Documented fallback, with `get_activity_history`, when `search_activities` is unavailable.
    While the primary is up, prefer `search_activities` with `include_description` for note
    text. When it 404s, `get_activity_history` yields a truncated gist and this tool is how
    you read the full body.

    The attachment list is this tool's one unique capability versus `search_activities`, which
    only publishes `attachments_count`. Pass `activity_id` from get_activity_history
    (meeting, call, note, or document — not a history email) or the `id` from a
    search_activities row — never invent one. Unlike the timeline's `gist` (truncated to a
    token budget), `body` here is the FULL converted text. `start`/`stop`/`location`/
    `time_zone` and `attendees` are only populated for a meeting/call record; a note,
    document, or email leaves them `None`/empty.
    """
    _ = ctx
    handle = ResourceIdentifierDto.from_activity_id(activity_id)
    logger.info(
        "activity_history.detail.get.start",
        extra={
            "activity_id": activity_id,
            "resource_type": handle.resource_type,
            "resource_id": handle.resource_id,
            "meeting_or_call": handle.is_meeting_or_call,
        },
    )
    result = await get_activity_detail_query.run(activity_id=activity_id, handle=handle)
    logger.info(
        "activity_history.detail.get.completed",
        extra={
            "activity_id": activity_id,
            "type": result.type,
            "attendees": len(result.attendees),
            "has_body": bool(result.body),
        },
    )
    return result
