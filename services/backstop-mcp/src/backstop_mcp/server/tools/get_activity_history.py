"""`get_activity_history`: party resolution plus concurrent stream fan-out.

On a `type="first"` request, resolves the party (`party_type` + `party_id`/`search`, exactly like
`get_person`/`get_organization`), then fetches the party record and every requested stream's first
page. On a `type="next"` request, `search_type` / `entity_id` / per-stream continuations are echoed
from a prior response — no resolve, no `/quick-search` round trip — and only those streams are
re-fetched.

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
    ActivityGroup,
    ActivityHistoryResolvedResponse,
    ActivityPage,
    ActivityType,
    EmailPage,
    TimelineRecord,
    fetch_activities_page_by_type,
    group_page,
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
    """Fetch a party's activity streams: meetings, calls, notes, emails, and documents.

    Pass `request.type="first"` with `party_type` plus a trusted `party_id` (from a prior resolve
    echo — never invent or guess one) or `search` to start. Default `activity_types` are all five
    streams including `document`. The response is `groups`: one entry per requested stream, not a
    single merged timeline. Each group's `date_range` is that page's span (min/max `occurred_at`
    among its dated items), not a cumulative window.

    To continue, call again with `request.type="next"`, echoing `resolved.search_type`,
    `resolved.id` as `entity_id`, and a `next` map built from each `groups[type].next` that is
    present. Drop exhausted streams (`next` omitted, or null). A one-entry map deepens a
    single stream; several entries continue those streams together.

    Future-dated meetings and calls are included, not filtered — Backstop schedules carry real
    future `effectiveDate`s, so an upcoming meeting can appear at the top of its stream.

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
            "streams": list(args.continuations),
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
            limit=continuation.limit,
            offset=continuation.offset,
            since=continuation.since,
            until=continuation.until,
        )
        for activity_type, continuation in args.continuations.items()
    }
    activities = await asyncio.gather(*page_calls.values())
    pages: dict[ActivityType, ActivityPage | EmailPage] = dict(
        zip(page_calls.keys(), activities, strict=True)
    )

    gist_max_chars = get_activity_history_settings().gist_max_chars
    groups: dict[ActivityType, ActivityGroup[TimelineRecord]] = {}
    for activity_type, continuation in args.continuations.items():
        page = pages[activity_type]
        grouped = group_page(
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
        groups[activity_type] = grouped.model_copy(update={"items": wire_items})

    attributes = document.data.attributes
    employments = get_employment_index_factory().index(**entity_relationships(document)).links()
    open_streams = [
        activity_type for activity_type, group in groups.items() if group.next is not None
    ]

    logger.info(
        "activity_history.get.completed",
        extra={
            "segment": args.segment,
            "entity_id": args.entity_id,
            "streams": list(groups),
            "employments": len(employments),
            "open_streams": open_streams,
        },
    )
    return tool_result(
        ActivityHistoryResolvedResponse(
            resolved=party_response(
                args.party, attributes=attributes.model_dump(by_alias=True, exclude_none=True)
            ),
            groups=groups,
            as_of=as_of_response(extract_as_of(attributes)),
            employments=employments,
        ),
        exclude_none=True,
    )
