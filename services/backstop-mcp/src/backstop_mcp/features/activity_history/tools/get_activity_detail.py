"""`get_activity_detail`: full converted body, meeting specifics, and attendees for one activity.

`activity_id` alone is a complete, self-sufficient handle — no party resolution needed. It is the
composite `{resourceType}_{resourceId}` a timeline record carries, so decoding it yields both the
bare resource id every detail endpoint wants and the resource type that says which endpoints
apply (see `ResourceIdentifierDto`).

For a meeting/call all three fetches — the detail record, the meeting specifics, and the
attendees — run CONCURRENTLY via `asyncio.gather`, mirroring `get_activity_history`'s stream
fan-out rather than gating the two `/meeting-or-calls` calls on the detail response. A note or
document is one request: both `/meeting-or-calls` paths 404 for a resource id that is not a
meeting/call.

A stale or invented `activity_id` raises rather than returning a bespoke not-found response,
matching `get_person`/`get_activity_history`'s convention that it must only ever be a value the
caller got from a prior timeline response. A handle that is not `{resourceType}_{resourceId}` at
all fails locally as a `ToolError`; one that is well-formed but unknown becomes a 404
`BackstopApiError` (`/entity-activity-details` answers 200 with null primary data for those, which
`BackstopApiResourceDocument.require_data` converts).
"""

import asyncio
import logging
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client
from backstop_mcp.features.activity_history import (
    ActivityDetailResponse,
    ResourceIdentifierDto,
    fetch_activity_detail,
    fetch_attendees,
    fetch_meeting_specifics,
)
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
                "The `activity_id` of one meeting, call, note, or document from a prior "
                "get_activity_history response. Never invent or guess one — an unknown id "
                "raises rather than returning a not-found response."
            ),
        ),
    ],
    client: BackstopClient = Depends(get_backstop_client),
) -> ActivityDetailResponse:
    """Fetch one activity's full body, meeting specifics, and attendees by `activity_id`.

    `activity_id` must come from a prior `get_activity_history` response — never invent or
    guess one. Unlike the timeline's `gist` (truncated to a token budget), `body` here is the
    FULL converted text — use this specifically when the timeline record's `gist_truncated`
    flag indicated more content exists. `start`/`stop`/`location`/`time_zone` and `attendees`
    are only populated for a meeting/call record; a note or document leaves them `None`/empty.
    """
    _ = ctx
    handle = ResourceIdentifierDto.from_activity_id(activity_id)
    resource_id = handle.resource_id
    logger.info(
        "activity_history.detail.get.start",
        extra={
            "activity_id": activity_id,
            "resource_type": handle.resource_type,
            "resource_id": resource_id,
            "meeting_or_call": handle.is_meeting_or_call,
        },
    )
    if handle.is_meeting_or_call:
        detail, specifics, attendees = await asyncio.gather(
            fetch_activity_detail(client, resource_id=resource_id),
            fetch_meeting_specifics(client, resource_id=resource_id),
            fetch_attendees(client, resource_id=resource_id),
        )
    else:
        logger.debug(
            "activity_history.detail.get.skip_meeting_fetches",
            extra={"activity_id": activity_id, "resource_type": handle.resource_type},
        )
        detail = await fetch_activity_detail(client, resource_id=resource_id)
        specifics = None
        attendees = ()

    logger.info(
        "activity_history.detail.get.completed",
        extra={
            "activity_id": activity_id,
            "type": detail.type,
            "attendees": len(attendees),
            "has_body": detail.description is not None,
        },
    )
    return ActivityDetailResponse.from_detail(
        activity_id=activity_id, detail=detail, specifics=specifics, attendees=attendees
    )
