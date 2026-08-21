"""`get_activity_history`: party resolution plus concurrent stream fan-out.

On a `type="first"` request, resolves the party (`search_type` + `party_id`/`search`, exactly like
`get_person`/`get_organization`), then fetches the party record and every requested stream's first
page. On a `type="next"` request, `search_type` / `entity_id` / per-stream continuations are echoed
from a prior response — no resolve, no `/quick-search` round trip — and only those streams are
re-fetched.

The party record is fetched first (name + `as_of` provenance). Active stream fetches then go
through one `asyncio.gather` call so a partial upstream failure fails the whole tool call rather
than silently dropping a stream (see the design doc's Error Handling section).
"""

import asyncio
import logging
from collections.abc import Coroutine
from urllib.parse import quote

from fastmcp import Context
from fastmcp.tools import tool
from mcp.types import ToolAnnotations

from backstop_mcp.backstop_client import BackstopApiResourceDocument
from backstop_mcp.features.activity_history import (
    ActivityGroupResponse,
    ActivityHistoryResolvedResponse,
    ActivityPageDto,
    ActivityType,
    EmailPageDto,
    GetActivityHistoryResponse,
    ResolvedPartyAsOfResponse,
    TimelineRecord,
    fetch_activities_page,
    group_activity_page,
    to_timeline_record,
)
from backstop_mcp.models import published_output_schema
from backstop_mcp.server.runtime import get_activity_history_settings, get_backstop_client
from backstop_mcp.server.tools.utils.activity_history import (
    ActivityHistoryFirstPageInput,
    ActivityHistoryNextPageInput,
    ActivityHistoryPageInput,
    FetchArgs,
    PartyRecordResponse,
    extract_fetch_activity_history_args,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ActivityHistoryFirstPageInput",
    "ActivityHistoryNextPageInput",
    "ActivityHistoryPageInput",
    "get_activity_history",
]


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    output_schema=published_output_schema(GetActivityHistoryResponse),
)
async def get_activity_history(
    ctx: Context,
    request: ActivityHistoryPageInput,
) -> GetActivityHistoryResponse:
    """Fetch a party's activity streams: meetings, calls, notes, emails, and documents.

    Pass `request.type="first"` with `search_type` plus a trusted `party_id` (from a prior resolve
    echo — never invent or guess one) or `search` to start. When retrying with `party_id`, pass
    that resolve's `search_type` — a contact or employee id is not a people id. Default
    `activity_types` are all five streams including
    `document`. The response is `groups`: one entry per requested stream, not a single merged
    timeline. Each group's `date_range` is that page's span (min/max `occurred_at` among its
    dated items), not a cumulative window.

    To continue, call again with `request.type="next"`, echoing `resolved.search_type`,
    `resolved.id` as `entity_id`, and a `next` map built from each `groups[type].next` that is
    present. Drop exhausted streams (`next` omitted, or null). A one-entry map deepens a
    single stream; several entries continue those streams together.

    Future-dated meetings and calls are included, not filtered — Backstop schedules carry real
    future `effectiveDate`s, so an upcoming meeting can appear at the top of its stream.

    There is no default date window: omitting `since`/`until` returns the newest activity in
    each requested stream regardless of age, which may be old — activity history in this CRM is
    often sparse.

    `resolved.as_of` is plain provenance from the party's own record; relay it, do not treat
    record age as a staleness verdict.
    """
    client = await get_backstop_client()
    args = await extract_fetch_activity_history_args(ctx, client, request)
    if not isinstance(args, FetchArgs):
        return args

    logger.info(
        "activity_history.get.start",
        extra={
            "segment": args.segment,
            "entity_id": args.entity_id,
            "streams": list(args.continuations),
        },
    )
    party_path = f"/{args.segment}/{quote(args.entity_id, safe='')}"
    document = await client.get(
        party_path,
        schema=BackstopApiResourceDocument[PartyRecordResponse],
    )
    page_calls: dict[ActivityType, Coroutine[None, None, ActivityPageDto | EmailPageDto]] = {
        activity_type: fetch_activities_page(
            client,
            activity_type=activity_type,
            segment=args.segment,
            entity_id=args.entity_id,
            limit=continuation.limit,
            offset=continuation.offset,
            since=continuation.since,
            until=continuation.until,
        )
        for activity_type, continuation in args.continuations.items()
    }
    activities = await asyncio.gather(*page_calls.values())
    pages: dict[ActivityType, ActivityPageDto | EmailPageDto] = dict(
        zip(page_calls.keys(), activities, strict=True)
    )

    gist_max_chars = get_activity_history_settings().gist_max_chars
    groups: dict[ActivityType, ActivityGroupResponse[TimelineRecord]] = {}
    for activity_type, continuation in args.continuations.items():
        page = pages[activity_type]
        grouped = group_activity_page(
            page.items,
            activity_type=activity_type,
            end_of_stream=page.end_of_stream,
            limit=continuation.limit,
            offset=continuation.offset,
            since=continuation.since,
            until=continuation.until,
        )
        wire_items = tuple(
            to_timeline_record(item, gist_max_chars=gist_max_chars) for item in grouped.items
        )
        groups[activity_type] = ActivityGroupResponse(
            activity_type=grouped.activity_type,
            items=wire_items,
            date_range=grouped.date_range,
            next=grouped.next,
        )

    attributes = document.require_data(path=party_path).attributes
    open_streams = [
        activity_type for activity_type, group in groups.items() if group.next is not None
    ]

    logger.info(
        "activity_history.get.completed",
        extra={
            "segment": args.segment,
            "entity_id": args.entity_id,
            "streams": list(groups),
            "open_streams": open_streams,
        },
    )
    return ActivityHistoryResolvedResponse(
        resolved=ResolvedPartyAsOfResponse.from_party(args.party, attributes=attributes),
        groups=groups,
    )
