"""`search_activities`: firm-wide or party activity search over `POST /entity-activities`.

Primary path for meetings, calls, notes, emails, and documents. Undocumented UI search;
`get_activity_history` is the documented fallback when this endpoint is missing. Tag filters
here are OR; REST activity-tag filters are AND.
"""

import logging
from collections.abc import Sequence
from datetime import date
from typing import Annotated, Literal

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import (
    BackstopAuthError,
    BackstopClient,
    BackstopRateLimitError,
)
from backstop_mcp.dependencies import get_backstop_client
from backstop_mcp.features.activity_history import (
    ENTITY_ACTIVITY_TYPES,
    MAX_RETRIEVABLE,
    ActivityAggregateBy,
    EntityActivityType,
    GetSearchActivitiesResponse,
    SearchActivitiesResolvedResponse,
    SearchActivitiesUnavailableResponse,
    aggregate_entity_activities,
    fetch_entity_activities,
    party_bean,
)
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver import (
    ResolvedPartyResponse,
    resolve_party,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import Resolved
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ROWS = 100
_DESCRIPTION_MAX_ROWS = 50
_MAX_ROWS = 1_000
_DEFAULT_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "type",
        "title",
        "effective_date",
        "short_description",
        "associated_with",
        "tags",
        "attendees",
        "author",
        "meeting_type",
        "attachments_count",
    }
)
_FALLBACK_MESSAGE = (
    "POST /entity-activities is undocumented and did not answer. Call get_activity_history "
    "with a resolved party instead. That fallback is party-scoped only — there is no "
    "documented firm-wide activity collection, so a firm-wide question must be narrowed "
    "to a party rather than treated as 'no activity exists'."
)

SearchMode = Literal["rows", "aggregate"]
SearchRowField = Literal[
    "id",
    "type",
    "activity_type",
    "title",
    "effective_date",
    "created_at",
    "modified_at",
    "start",
    "stop",
    "time_zone",
    "location",
    "meeting_type",
    "short_description",
    "description",
    "attachments_count",
    "author",
    "attendees",
    "tags",
    "associated_with",
    "from_address",
    "to_addresses",
]


def _is_wide_sweep(
    *, associated_withs: Sequence[str], activity_tags: Sequence[str], authors: Sequence[str]
) -> bool:
    return not associated_withs and not activity_tags and not authors


@tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    output_schema=published_output_schema(GetSearchActivitiesResponse),
)
async def search_activities(
    ctx: Context,
    start_date: Annotated[
        date,
        Field(description="Inclusive start of the mandatory effective-date window."),
    ],
    end_date: Annotated[
        date,
        Field(description="Inclusive end of the mandatory effective-date window."),
    ],
    search_type: Annotated[
        SearchType | None,
        Field(
            default=None,
            description=(
                "Party collection when scoping to one person or organization. Required with "
                "`party_id` or `search`. Omit with both of those for a firm-wide search."
            ),
        ),
    ] = None,
    party_id: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Trusted Backstop Party ID from a prior resolve echo. Sent as "
                "`associatedWiths: PartyBean_{id}`. Never invent one. Exactly one of "
                "`party_id` or `search` when scoping to a party."
            ),
        ),
    ] = None,
    search: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Name or email to resolve when no trusted `party_id` is available. Exactly "
                "one of `party_id` or `search` when scoping to a party."
            ),
        ),
    ] = None,
    types: Annotated[
        list[EntityActivityType] | None,
        Field(
            default=None,
            description=(
                "Activity streams to include. Default is every stream this endpoint serves: "
                "meeting_call, meeting, document, email, email_blast, note. Within this list "
                "the filter is OR."
            ),
        ),
    ] = None,
    activity_tag_ids: Annotated[
        list[str] | None,
        Field(
            default=None,
            description=(
                "Tag ids from list_activity_tags. This endpoint treats the list as OR "
                "(union). REST get_activity_history `activity_tag_ids` is AND. Do not assume "
                "they match."
            ),
        ),
    ] = None,
    authors: Annotated[
        list[str] | None,
        Field(
            default=None,
            description=(
                "Author emails. Matched as email, not a login and not a display name. "
                "Several values are OR; combining authors with tags is AND across keys."
            ),
        ),
    ] = None,
    include_description: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "Opt in to full note text (~25× row size). Capped at 50 rows, refused with "
                "`mode=aggregate`, and refused on a wide sweep (no party, no tags, no "
                "authors)."
            ),
        ),
    ] = False,
    mode: Annotated[
        SearchMode,
        Field(
            default="rows",
            description=(
                "`rows` returns activity bodies, capped by `max_rows`. `aggregate` returns "
                "counts grouped by `group_by` so a counting question never pays for row bodies."
            ),
        ),
    ] = "rows",
    group_by: Annotated[
        ActivityAggregateBy | None,
        Field(
            default=None,
            description=(
                "Required when `mode=aggregate`: type, tag, party, or period (YYYY-MM). "
                "Must be omitted in rows mode."
            ),
        ),
    ] = None,
    max_rows: Annotated[
        int,
        Field(
            default=_DEFAULT_MAX_ROWS,
            ge=1,
            le=_MAX_ROWS,
            description=(
                f"Maximum row bodies to return in rows mode. Aggregate mode scans up to the "
                f"{MAX_RETRIEVABLE} ceiling regardless. include_description caps this at 50 "
                "and is refused in aggregate mode."
            ),
        ),
    ] = _DEFAULT_MAX_ROWS,
    fields: Annotated[
        list[SearchRowField] | None,
        Field(
            default=None,
            description=(
                "Sparse row fields. Default is id, type, title, effective_date, "
                "short_description, associated_with, tags, attendees, author, meeting_type, "
                "attachments_count. `description` is only filled when include_description "
                "is true."
            ),
        ),
    ] = None,
    client: BackstopClient = Depends(get_backstop_client),
) -> GetSearchActivitiesResponse:
    """Search activities firm-wide or for one party: meetings, calls, notes, emails, documents.

    Pass a mandatory `start_date` / `end_date` window. Optionally scope to a party
    (`search_type` plus `party_id` or `search`), restrict `types`, filter `activity_tag_ids`
    (OR, unlike get_activity_history), and filter `authors` by email.

    This is the primary activity tool. It is an undocumented UI search (`POST /entity-activities`)
    and may 404 on another tenant — that is not "no activity exists". The failure payload names
    `get_activity_history`, which is party-scoped only. `results: []` with status resolved is
    genuinely none in that window.

    Counts are visible to you, not firm-wide. `totalCount` saturates at 10000; this tool clamps
    `pageNum × pageSize` before requesting so it never provokes that 500, and returns the
    partial set with a disclaimer. Tag filters here are OR; REST tag filters are AND.

    `mode=aggregate` with `group_by` answers a counting question without row bodies.
    `include_description` is opt-in, capped, refused in aggregate mode, and refused on a wide
    sweep. `attachments_count` is a count only — `get_activity_detail` lists the files.
    """
    if start_date > end_date:
        raise ValueError("start_date must not be after end_date")
    if mode == "aggregate" and group_by is None:
        raise ValueError("group_by is required when mode is aggregate")
    if mode == "rows" and group_by is not None:
        raise ValueError("group_by is only used when mode is aggregate")
    if include_description and mode == "aggregate":
        raise ValueError(
            "include_description is refused in aggregate mode; counts do not use row bodies"
        )
    party_selector = party_id is not None or search is not None
    if search_type is None and party_selector:
        raise ValueError("search_type is required when party_id or search is provided")
    if search_type is not None and not party_selector:
        raise ValueError("party_id or search is required when search_type is provided")

    resolved_party: ResolvedPartyResponse | None = None
    associated_withs: tuple[str, ...] = ()
    if search_type is not None:
        outcome = await resolve_party(
            ctx, client, search_type=search_type, party_id=party_id, search=search
        )
        if not isinstance(outcome, Resolved):
            return unresolved_party_response(outcome)
        resolved_party = ResolvedPartyResponse.from_party(outcome.value)
        associated_withs = (party_bean(outcome.value.id),)

    tag_ids = tuple(activity_tag_ids) if activity_tag_ids else ()
    author_emails = tuple(authors) if authors else ()
    selected_types: tuple[EntityActivityType, ...] = (
        tuple(types) if types else ENTITY_ACTIVITY_TYPES
    )
    if include_description and _is_wide_sweep(
        associated_withs=associated_withs, activity_tags=tag_ids, authors=author_emails
    ):
        raise ValueError(
            "include_description is refused on a wide sweep; pass a party, "
            + "activity_tag_ids, or authors, or leave include_description false"
        )

    row_cap = min(max_rows, _DESCRIPTION_MAX_ROWS) if include_description else max_rows
    # `description` is added to the *default* set when it was opted into, and never forced onto
    # an explicit `fields` list: a caller who names the fields they want has said what they want.
    if fields:
        selected_fields = frozenset(fields)
    elif include_description:
        selected_fields = _DEFAULT_FIELDS | frozenset({"description"})
    else:
        selected_fields = _DEFAULT_FIELDS

    logger.info(
        "activity_history.search.start",
        extra={
            "mode": mode,
            "include_description": include_description,
            "party": None if resolved_party is None else resolved_party.id,
        },
    )
    try:
        fetch = await fetch_entity_activities(
            client,
            start_date=start_date,
            end_date=end_date,
            types=selected_types,
            associated_withs=associated_withs,
            activity_tags=tag_ids,
            authors=author_emails,
            include_description=include_description,
            max_rows=None if mode == "aggregate" else row_cap,
        )
    except (BackstopAuthError, BackstopRateLimitError):
        # Neither is "this endpoint is unavailable". A dead credential fails the documented
        # fallback the same way, and a rate limit is a "slow down" that naming a second tool
        # would answer with more load.
        raise
    except Exception as exc:
        # Broad on purpose, matching `fetch_holdings`: HTTP status, transport timeout and
        # schema-validation failure all mean the same thing here — the undocumented endpoint did
        # not answer usably. A `httpx.TimeoutException` reaches this frame raw (the client lets
        # transport errors out), and letting it propagate is the one path where the "name the
        # fallback" contract silently would not fire, on the failure an unbounded-payload UI
        # endpoint is likeliest to produce.
        logger.warning(
            "activity_history.search.primary_unavailable",
            extra={"error": f"{type(exc).__name__}: {exc}"},
        )
        return SearchActivitiesUnavailableResponse(message=_FALLBACK_MESSAGE)

    aggregates = ()
    if mode == "aggregate":
        assert group_by is not None
        aggregates = aggregate_entity_activities(fetch.rows, group_by=group_by)
    return SearchActivitiesResolvedResponse.from_fetch(
        fetch,
        mode=mode,
        fields=selected_fields,
        resolved=resolved_party,
        aggregates=aggregates,
        description_row_capped=include_description and max_rows > _DESCRIPTION_MAX_ROWS,
        ceiling=MAX_RETRIEVABLE,
    )
