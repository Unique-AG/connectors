"""`get_activity_detail`: full converted body, meeting specifics, and attendees for one activity.

`activity_id` alone is a complete, self-sufficient handle — no party resolution needed. Fetches
`entity-activity-details/{activity_id}` and, when `activity_id` looks like a meeting/call (the
`meeting-or-calls_` prefix — the only shape that ever carries attendees on this instance),
`/meeting-or-calls/{resourceId}/attendees` CONCURRENTLY via `asyncio.gather`, mirroring
`get_activity_history`'s stream fan-out rather than gating the attendees fetch on the details
response. The attendees path uses the bare resource id (prefix stripped), not the polymorphic
timeline id.

Caveat: the wire field names this depends on for `entity-activity-details`'s meeting specifics
and the attendees shape were not byte-verified against a live Backstop instance the way this
feature's other endpoints were — see `fetch_activity_detail.py`'s module docstring for exactly
which spellings are guesses. A wrong guess degrades to `None`/empty rather than crashing.

A 404 from Backstop (an invented or stale `activity_id`) propagates as `BackstopApiError` — no
bespoke not-found response, matching `get_person`/`get_activity_history`'s convention that
`activity_id` must only ever be a value the caller got from a prior timeline response.
"""

import asyncio
import logging
from typing import Annotated

from fastmcp import Context
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.activity_history import (
    ActivityDetail,
    ActivityDetailResponse,
    Attendee,
    fetch_activity_detail,
    fetch_attendees,
    is_meeting_or_call,
    to_activity_detail_response,
)
from backstop_mcp.models import published_output_schema
from backstop_mcp.server.runtime import get_backstop_client

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
) -> ActivityDetailResponse:
    """Fetch one activity's full body, meeting specifics, and attendees by `activity_id`.

    `activity_id` must come from a prior `get_activity_history` response — never invent or
    guess one. Unlike the timeline's `gist` (truncated to a token budget), `body` here is the
    FULL converted text — use this specifically when the timeline record's `gist_truncated`
    flag indicated more content exists. `start`/`stop`/`location`/`time_zone` and `attendees`
    are only populated for a meeting/call record; a note or document leaves them `None`/empty.
    """
    _ = ctx
    client = await get_backstop_client()
    detail: ActivityDetail
    attendees: tuple[Attendee, ...]
    fetch_attendees_for = is_meeting_or_call(activity_id)
    logger.info(
        "activity_history.detail.get.start",
        extra={"activity_id": activity_id, "fetch_attendees": fetch_attendees_for},
    )
    if fetch_attendees_for:
        detail, attendees = await asyncio.gather(
            fetch_activity_detail(client, activity_id=activity_id),
            fetch_attendees(client, activity_id=activity_id),
        )
    else:
        logger.debug(
            "activity_history.detail.get.skip_attendees",
            extra={"activity_id": activity_id},
        )
        detail = await fetch_activity_detail(client, activity_id=activity_id)
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
    return to_activity_detail_response(detail, attendees)
