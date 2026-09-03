"""`get_activity_history`: party resolution plus concurrent stream fan-out.

On a `type="first"` request, resolves the party (`search_type` + `party_id`/`search`, exactly like
`get_person`/`get_organization`), then fetches the party record and every requested stream's first
page. On a `type="next"` request, `search_type` / `entity_id` / per-stream continuations are echoed
from a prior response — no resolve, no `/quick-search` round trip — and only those streams are
re-fetched.

The party record is fetched first (name + `as_of` provenance). Active stream fetches then go
through one `asyncio.gather` call. A 5xx or transport failure still fails the whole call.
A 403 on one stream (Backstop refusing a linked entity) is reported on that group and the
other streams are kept — otherwise a forbidden document/email wipes a successful calls page.
"""

import logging

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.activity_history import (
    ActivityHistorySettings,
    GetActivityHistoryQuery,
    GetActivityHistoryResponse,
    get_activity_history_settings,
)
from backstop_mcp.features.activity_history.dependencies import get_activity_history_query_factory
from backstop_mcp.models import published_output_schema

from ._page_input import (
    ActivityHistoryFirstPageInput,
    ActivityHistoryNextPageInput,
    ActivityHistoryPageInput,
    FetchArgs,
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
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    activity_history: ActivityHistorySettings = Depends(get_activity_history_settings),
    get_activity_history_query: GetActivityHistoryQuery = Depends(
        get_activity_history_query_factory
    ),
) -> GetActivityHistoryResponse:
    """Party-scoped stream pages. Do not start here — always use `search_activities` first.

    Documented fallback when `search_activities` is unavailable (that primary is an undocumented
    UI search and may 404 on another tenant). Use `search_activities` for a date window, activity
    types, tags, authors, note text, or a firm-wide question. This tool pages one party's REST
    streams only when that primary is missing. REST `activity_tag_ids` are AND;
    `search_activities` tag filters are OR. A 403 on one stream (empty `items` plus `error`) is
    not "no notes" — retry those types on `search_activities` with `include_description`.

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

    Each meeting, call, note, and document row includes `tags` when Backstop side-loads them.
    `/activities` does not publish `regarding` or `attendees` on this collection (those field
    and include names 400); they stay empty on history rows. Pass `activity_tag_ids` from
    list_activity_tags to keep only rows that carry all of those tags. Emails have no tags and
    no includes; they are omitted when `activity_tag_ids` is set.

    `resolved.as_of` is plain provenance from the party's own record; relay it, do not treat
    record age as a staleness verdict.

    Pass a meeting, call, note, or document row's `activity_id` to `get_activity_detail` for
    the full untruncated body and the attachment list. History email ids are from `/emails`
    and do not work there — use `search_activities` for email body. `search_activities` rows
    use the same argument.
    """
    args = await extract_fetch_activity_history_args(
        ctx, client, request, page_size=activity_history.page_size
    )
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
    result = await get_activity_history_query.run(
        segment=args.segment,
        entity_id=args.entity_id,
        party=args.party,
        continuations=args.continuations,
        gist_max_chars=activity_history.gist_max_chars,
    )
    open_streams = [
        activity_type for activity_type, group in result.groups.items() if group.next is not None
    ]
    logger.info(
        "activity_history.get.completed",
        extra={
            "segment": args.segment,
            "entity_id": args.entity_id,
            "streams": list(result.groups),
            "open_streams": open_streams,
        },
    )
    return result
