"""`search_activities`: firm-wide or party activity search over `POST /entity-activities`.

Primary path for meetings, calls, notes, emails, and documents. The swagger entry calls
that POST a create; it is a search. `get_activity_history` is the party-scoped fallback
when this endpoint does not answer. Tag filters here are OR; REST activity-tag filters
are AND.
"""

import logging
from collections.abc import Sequence
from datetime import date
from typing import Annotated, Literal

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import InputRequiredResult, ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopAuthError, BackstopRateLimitError
from backstop_mcp.features.activity_history import (
    ENTITY_ACTIVITY_TYPES,
    MAX_RETRIEVABLE,
    ActivityAggregateBy,
    EntityActivityDto,
    EntityActivityType,
    GetSearchActivitiesResponse,
    SearchActivitiesQuery,
    SearchActivitiesResolvedResponse,
    SearchActivitiesUnavailableResponse,
    aggregate_entity_activities,
)
from backstop_mcp.features.activity_history.dependencies import get_search_activities_query_factory
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver import (
    ResolvedPartyResponse,
    ResolvePartyQuery,
    get_resolve_party_query_factory,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import Resolved, elicit_if_ambiguous, input_required
from backstop_mcp.features.ui_links import (
    BuildEntityLinkUtil,
    activity_link_target,
    get_build_entity_link_util_factory,
)
from backstop_mcp.models import published_output_schema
from backstop_mcp.utils import date_window

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ROWS = 100
_DESCRIPTION_MAX_ROWS = 50
_MAX_ROWS = 1_000
_DEFAULT_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "activity_id",
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
    "POST /entity-activities did not answer. Call get_activity_history with a resolved "
    "party instead. That fallback is party-scoped only — the REST activity streams have "
    "no firm-wide collection, so a firm-wide question must be narrowed to a party rather "
    "than treated as 'no activity exists'."
)

SearchMode = Literal["rows", "aggregate"]
SearchRowField = Literal[
    "id",
    "activity_id",
    "url",
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
    *, party_id: str | None, activity_tags: Sequence[str], authors: Sequence[str]
) -> bool:
    return party_id is None and not activity_tags and not authors


def _row_urls(
    rows: Sequence[EntityActivityDto], build_entity_link_util: BuildEntityLinkUtil
) -> dict[str, str | None]:
    """Row id → CRM URL. A row whose `type` has no CRM page is absent, which reads as None."""
    urls: dict[str, str | None] = {}
    for row in rows:
        target = activity_link_target(
            activity_type=row.type,
            entity_activity_details_id=row.id,
        )
        if target is None:
            continue
        urls[row.id] = build_entity_link_util.canonical_url(target=target)
    return urls


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(GetSearchActivitiesResponse),
)
async def search_activities(
    ctx: Context,
    start_date: Annotated[
        date | None,
        Field(
            default=None,
            description=(
                "Inclusive start of the effective-date window. Omit to use one year before "
                "`end_date` (or before today when `end_date` is also omitted)."
            ),
        ),
    ] = None,
    end_date: Annotated[
        date | None,
        Field(
            default=None,
            description=(
                "Inclusive end of the effective-date window. Omit to use today. A call with "
                "only `end_date` (e.g. 2024-12-31) still runs — `start_date` fills in as one "
                "year earlier."
            ),
        ),
    ] = None,
    search_type: Annotated[
        SearchType | None,
        Field(
            default=None,
            description=(
                "Required when passing `party_id` or `search` — never pass a `party_id` "
                "without this. Party collection: organizations, people, contacts, or "
                "employees. Omit with both of those for a firm-wide search."
            ),
        ),
    ] = None,
    party_id: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Trusted Backstop party id from a prior resolve echo. Always pass together "
                "with `search_type` — `party_id` alone is rejected. Never invent one. Exactly "
                "one of `party_id` or `search` when scoping to a party."
            ),
        ),
    ] = None,
    search: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Name or email to resolve when no trusted `party_id` is available. Always "
                "pass together with `search_type`. Exactly one of `party_id` or `search` "
                "when scoping to a party."
            ),
        ),
    ] = None,
    types: Annotated[
        list[EntityActivityType] | None,
        Field(
            default=None,
            description=(
                "Allowed tokens: meeting_call, meeting, document, email, email_blast, note. "
                "Calls are `meeting_call` — `get_activity_history` uses `call` for the same "
                "stream. Default is every stream this endpoint serves. Within this list the "
                "filter is OR."
            ),
        ),
    ] = None,
    activity_tag_ids: Annotated[
        list[str] | None,
        Field(
            default=None,
            description=(
                "Pass every id `list_activity_tags` returned for the term; the list is OR. "
                "Tag names carry prefixes (for example 'XY: Follow-up'), so requiring an "
                "exact name misses the tag. REST get_activity_history `activity_tag_ids` is AND."
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
                "Opt in to the full body text (much larger rows). Caps rows at 50; refused "
                "with `mode=aggregate` and on a wide sweep (no party, no tags, no authors)."
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
                f"{MAX_RETRIEVABLE} ceiling on a scoped search and is refused on a wide sweep."
            ),
        ),
    ] = _DEFAULT_MAX_ROWS,
    fields: Annotated[
        list[SearchRowField] | None,
        Field(
            default=None,
            description=(
                "Sparse row fields. Default is id, activity_id, type, title, effective_date, "
                "short_description, associated_with, tags, attendees, author, meeting_type, "
                "attachments_count. `description` is only filled when include_description "
                "is true. Select `url` when the answer will link to the activities — it is "
                "off by default so a wide sweep stays cheap. Pass `activity_id` to "
                "get_activity_detail."
            ),
        ),
    ] = None,
    resolve_party_query: ResolvePartyQuery = Depends(get_resolve_party_query_factory),
    search_activities_query: SearchActivitiesQuery = Depends(get_search_activities_query_factory),
    build_entity_link_util: BuildEntityLinkUtil = Depends(get_build_entity_link_util_factory),
) -> GetSearchActivitiesResponse | InputRequiredResult:
    """Search activities firm-wide or for one party: meetings, calls, notes, emails, documents.

    Always start here when the question has a date window. Pass `start_date` and `end_date`;
    omitting `start_date` uses one year before `end_date`, omitting `end_date` uses today.
    Optionally scope to a party (`search_type` plus `party_id` or `search` — a `party_id`
    without `search_type` is rejected), restrict `types`,
    filter `activity_tag_ids` (OR, unlike get_activity_history), and filter `authors` by email.

    Call like: {"search_type": "organizations",
    "party_id": "<id from prior resolve echo>",
    "types": ["meeting_call", "meeting", "note"]}

    This is the primary activity tool; `get_activity_history` is fallback only. This search
    may be unavailable (`status` `unavailable`); that is not "no activity". Use
    get_activity_history (party-scoped) instead, not a retry of this tool. An empty `rows`
    list with status resolved is genuinely none in that window.

    Counts cover only what this credential can see. A set larger than the 10000 ceiling
    comes back partial, with a disclaimer on `coverage`.

    `mode=aggregate` with `group_by` answers a counting question without row bodies.
    A party missing from a firm-wide row sample is not
    inactive; for "who has had no activity since X" use get_last_activity_for_parties.
    `attachments_count` is a count only — pass the row `activity_id` (or `id`) to
    `get_activity_detail` for the names. Do not assume what the files are. Meeting, call,
    note, and document rows from `get_activity_history` use the
    same argument; history email ids do not. Attendee columns use the structured
    `attendees` names on these rows, not names read out of the title or body.
    """
    start_date, end_date = date_window(start_date, end_date, today=date.today())
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
    scoped_party_id: str | None = None
    if search_type is not None:
        outcome = await resolve_party_query.run(
            search_type=search_type, party_id=party_id, search=search
        )
        outcome = await elicit_if_ambiguous(ctx, outcome)
        if input_required(outcome):
            return outcome
        if not isinstance(outcome, Resolved):
            return unresolved_party_response(outcome)
        resolved_party = ResolvedPartyResponse.from_party(outcome.value)
        scoped_party_id = outcome.value.id

    tag_ids = tuple(activity_tag_ids) if activity_tag_ids else ()
    author_emails = tuple(authors) if authors else ()
    selected_types: tuple[EntityActivityType, ...] = (
        tuple(types) if types else ENTITY_ACTIVITY_TYPES
    )
    wide = _is_wide_sweep(party_id=scoped_party_id, activity_tags=tag_ids, authors=author_emails)
    if include_description and wide:
        raise ValueError(
            "include_description is refused on a wide sweep; pass a party, "
            + "activity_tag_ids, or authors, or leave include_description false"
        )
    if mode == "aggregate" and wide:
        raise ValueError(
            "mode=aggregate is refused on a wide sweep; pass a party, activity_tag_ids, "
            + "or authors, or use mode=rows"
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
        fetch = await search_activities_query.run(
            start_date=start_date,
            end_date=end_date,
            types=selected_types,
            party_id=scoped_party_id,
            resource_type=None if resolved_party is None else resolved_party.search_type,
            activity_tags=tag_ids,
            authors=author_emails,
            include_description=include_description,
            max_rows=None if mode == "aggregate" else row_cap,
        )
    except BackstopAuthError, BackstopRateLimitError:
        # Neither is "this endpoint is unavailable". A dead credential fails the documented
        # fallback the same way, and a rate limit is a "slow down" that naming a second tool
        # would answer with more load.
        raise
    except Exception as exc:
        # Broad on purpose, matching `GetHoldingsQuery`: HTTP status, transport timeout,
        # schema-validation failure, and a 401 that re-verified (`BackstopTransientAuthError`)
        # all mean the same thing here — the search did not answer usably. A
        # `httpx.TimeoutException` reaches this frame raw (the client lets transport errors
        # out), and letting it propagate is the one path where the "name the fallback" contract
        # silently would not fire, on the failure an unbounded-payload UI endpoint is likeliest
        # to produce.
        logger.warning(
            "activity_history.search.primary_unavailable",
            exc_info=exc,
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
        urls=_row_urls(fetch.rows, build_entity_link_util)
        if mode == "rows" and "url" in selected_fields
        else {},
        aggregates=aggregates,
        description_row_capped=include_description and max_rows > _DESCRIPTION_MAX_ROWS,
        ceiling=MAX_RETRIEVABLE,
    )
