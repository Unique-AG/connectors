"""`get_activity_history`: party resolution plus concurrent stream fan-out for a timeline.

On a `type="first"` request, resolves the party (`party_type` + `party_id`/`search`, exactly like
`get_person`/`get_organization`), then fetches the party record and every requested stream's first
page. On a `type="next"` request, the cursor already carries the full query state — no resolve, no
`/quick-search` round trip — and only the streams the cursor says are still open get re-fetched.

The party record is fetched first (it also side-loads employments). Active stream fetches then go
through one `asyncio.gather` call so a partial upstream failure fails the whole tool call rather
than silently dropping a stream (see the design doc's Error Handling section).
"""

import asyncio
import logging
from collections.abc import Coroutine
from urllib.parse import quote

from fastmcp import Context
from fastmcp.tools import tool
from mcp.types import CallToolResult, ToolAnnotations

from backstop_mcp.backstop_client import BackstopApiResourceDocument
from backstop_mcp.features.activity_history import (
    ActivityHistoryResolvedResponse,
    ActivityPage,
    ActivityType,
    EmailPage,
    encode_cursor,
    fetch_activities_page_by_type,
    merge_page,
    to_timeline_record,
)
from backstop_mcp.features.data_hygiene import (
    EntityRelationshipInclude,
    as_of_response,
    entity_relationships,
    extract_as_of,
)
from backstop_mcp.features.party_resolver import party_response
from backstop_mcp.server.runtime import (
    get_activity_history_settings,
    get_backstop_client,
    get_employment_index_factory,
)
from backstop_mcp.server.tools.results import tool_result
from backstop_mcp.server.tools.utils.get_activity_history_utils import (
    ActivityHistoryFirstPageInput,
    ActivityHistoryNextPageInput,
    ActivityHistoryPageInput,
    PartyAttributes,
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
)
async def get_activity_history(
    ctx: Context,
    request: ActivityHistoryPageInput,
) -> CallToolResult:
    """Fetch a party's activity timeline: meetings, calls, notes, and emails.

    Pass `request.type="first"` with `party_type` plus a trusted `party_id` (from a prior resolve
    echo — never invent or guess one) or `search` to start a timeline. To get more results, call
    again with `request.type="next"` and only `next_cursor` — the cursor already carries the full
    query state (party, streams, date bounds, per-stream pagination offsets).

    `document` activities are excluded by default; pass `activity_types` explicitly to include
    them. Records are ordered newest-first by `occurred_at`, with one wart: activity dates
    (meeting/call/note/document) are date-only and sort at midnight, while an email carries a
    real time-of-day timestamp — so on a day with both an email and a meeting/call/note, the
    email sorts above the other activity even if that activity happened earlier the same day.

    Future-dated meetings and calls are included, not filtered — Backstop schedules carry real
    future `effectiveDate`s, so an upcoming meeting can appear at the top of the timeline.

    There is no default date window: omitting `since`/`until` returns the newest activity in
    each requested stream regardless of age, which may be old — activity history in this CRM is
    often sparse.

    Side-loads `entityRelationships` for both person and organization parties and returns
    `employments` (current and former person↔organization links) — always relay them; do not
    present a person as a current contact at an organization whose link has `status="former"`
    unless the user explicitly asked for historical contacts. `as_of` is plain provenance from
    the party's own record; relay it, do not treat record age as a staleness verdict.
    """
    client = await get_backstop_client()
    args = await extract_fetch_activity_history_args(ctx, client, request)
    if isinstance(args, CallToolResult):
        return args

    logger.info(
        "activity_history.get.start",
        extra={
            "segment": args.segment,
            "entity_id": args.entity_id,
            "streams": list(args.active_activity_types),
            "limit": args.limit,
            "since": args.since.isoformat() if args.since is not None else None,
            "until": args.until.isoformat() if args.until is not None else None,
        },
    )
    document = await client.get(
        f"/{args.segment}/{quote(args.entity_id, safe='')}",
        params={"include": EntityRelationshipInclude.for_employment()},
        schema=BackstopApiResourceDocument[PartyAttributes],
    )
    page_calls: dict[ActivityType, Coroutine[None, None, ActivityPage | EmailPage]] = {
        activity_type: fetch_activities_page_by_type(
            client,
            activity_type=activity_type,
            segment=args.segment,
            entity_id=args.entity_id,
            limit=args.limit,
            offset=args.consumed.get(activity_type, 0),
            since=args.since,
            until=args.until,
        )
        for activity_type in args.active_activity_types
    }
    activities = await asyncio.gather(*page_calls.values())
    pages: dict[ActivityType, ActivityPage | EmailPage] = dict(
        zip(page_calls.keys(), activities, strict=True)
    )

    merged = merge_page(
        {activity_type: (page.items, page.end_of_stream) for activity_type, page in pages.items()},
        args.consumed,
    )
    records = [
        to_timeline_record(record, gist_max_chars=get_activity_history_settings().gist_max_chars)
        for record in merged.records
    ]
    next_cursor_out = encode_cursor(
        segment=args.segment,
        entity_id=args.entity_id,
        limit=args.limit,
        activity_types=args.activity_types,
        since=args.since,
        until=args.until,
        consumed=merged.consumed,
    )

    attributes = document.data.attributes
    employments = get_employment_index_factory().index(**entity_relationships(document)).links()

    logger.info(
        "activity_history.get.completed",
        extra={
            "segment": args.segment,
            "entity_id": args.entity_id,
            "records": len(records),
            "employments": len(employments),
            "has_next_cursor": next_cursor_out is not None,
            "open_streams": sorted(merged.consumed),
        },
    )
    return tool_result(
        ActivityHistoryResolvedResponse(
            resolved=party_response(
                args.party, attributes=attributes.model_dump(by_alias=True, exclude_none=True)
            ),
            records=records,
            next_cursor=next_cursor_out,
            as_of=as_of_response(extract_as_of(attributes)),
            employments=employments,
        ),
        exclude_none=True,
    )
