"""Request shapes and first/next → fetch-input helpers for `get_activity_history`."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Annotated, ClassVar, Literal

from fastmcp import Context
from mcp.types import CallToolResult
from pydantic import BaseModel, ConfigDict, Field

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.activity_history import (
    ActivityType,
    InvalidCursor,
    Segment,
    decode_cursor,
)
from backstop_mcp.features.data_hygiene import ProvenanceFields
from backstop_mcp.features.party_resolver import (
    ResolvedParty,
    resolve_party,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import Resolved
from backstop_mcp.server.runtime import get_activity_history_settings
from backstop_mcp.server.tools.results import tool_error, tool_result

logger = logging.getLogger(__name__)

_DEFAULT_ACTIVITY_TYPES: tuple[ActivityType, ...] = ("meeting", "call", "note", "email")


class ActivityHistoryFirstPageInput(BaseModel):
    """Start a new activity timeline for a party."""

    type: Literal["first"]
    party_type: Annotated[
        Literal["organization", "person"],
        Field(description="Which kind of party to fetch the timeline for."),
    ]
    party_id: Annotated[
        str | None,
        Field(
            description=(
                "Trusted Backstop Party ID from a prior resolve echo (`id` / `search_type` / "
                "`name`). Never invent or guess. Exactly one of `party_id` or `search` must be "
                "provided."
            ),
        ),
    ] = None
    search: Annotated[
        str | None,
        Field(
            description=(
                "Name or email to resolve when no trusted `party_id` is available. Exactly one "
                "of `party_id` or `search` must be provided."
            ),
        ),
    ] = None
    activity_types: Annotated[
        list[ActivityType] | None,
        Field(
            description=(
                "Which streams to fetch: any of meeting, call, note, document, email. Defaults "
                "to meeting, call, note, email — `document` is excluded unless listed here "
                "explicitly."
            ),
        ),
    ] = None
    since: Annotated[
        date | None,
        Field(
            description=(
                "Only include activity on or after this date. There is no default window: "
                "omitting both `since` and `until` returns the newest activity regardless of "
                "age, which may be old."
            ),
        ),
    ] = None
    until: Annotated[
        date | None,
        Field(
            description=(
                "Only include activity on or before this date. Future-dated meetings and calls "
                "are included, not filtered, when this is left unset."
            ),
        ),
    ] = None
    limit: Annotated[
        int | None,
        Field(
            gt=0,
            description=(
                "Page size per stream (not a total cap — a response can carry up to `limit` "
                "records per active stream). Defaults to this server's configured page size."
            ),
        ),
    ] = None


class ActivityHistoryNextPageInput(BaseModel):
    """Fetch the next page of a timeline already in progress."""

    type: Literal["next"]
    next_cursor: Annotated[
        str,
        Field(
            description=(
                "Opaque cursor from a prior `get_activity_history` response. Carries the full "
                "query state (party, streams, date bounds, per-stream offsets)."
            ),
        ),
    ]


type ActivityHistoryPageInput = Annotated[
    ActivityHistoryFirstPageInput | ActivityHistoryNextPageInput,
    Field(discriminator="type"),
]


class PartyAttributes(ProvenanceFields):
    """Minimal attributes this tool needs from the party fetch: a display name plus provenance.

    `extra="ignore"`, not `"allow"` — unlike `get_person`/`get_organization`, this tool never
    surfaces the raw attribute dump, only `name` (for the resolve echo) and provenance (for
    `as_of`).
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    name: str | None = None


@dataclass(frozen=True, slots=True)
class FetchArgs:
    """Mode-agnostic inputs for the concurrent party + activity-type fan-out."""

    segment: Segment
    entity_id: str
    party: ResolvedParty
    limit: int
    activity_types: tuple[ActivityType, ...]
    since: date | None
    until: date | None
    consumed: Mapping[ActivityType, int]
    active_activity_types: tuple[ActivityType, ...]


def segment_for(party_type: Literal["organization", "person"]) -> Segment:
    return "organizations" if party_type == "organization" else "people"


def effective_activity_types(
    activity_types: list[ActivityType] | None,
) -> tuple[ActivityType, ...]:
    if not activity_types:
        return _DEFAULT_ACTIVITY_TYPES
    return tuple(dict.fromkeys(activity_types))


async def extract_fetch_activity_history_args(
    ctx: Context,
    client: BackstopClient,
    request: ActivityHistoryFirstPageInput | ActivityHistoryNextPageInput,
) -> FetchArgs | CallToolResult:
    """Turn a first/next page input into shared fetch inputs, or an early tool result/error.

    Pydantic already validates/discriminates the wire shape (`ActivityHistoryPageInput`). This
    step is separate because it does async I/O: party resolve on `first`, cursor decode on `next`.
    """
    match request:
        case ActivityHistoryNextPageInput(next_cursor=next_cursor):
            try:
                decoded = decode_cursor(next_cursor)
            except InvalidCursor as exc:
                logger.warning(
                    "activity_history.args.invalid_cursor",
                    extra={"error": str(exc)},
                )
                return tool_error(str(exc))
            activity_types = decoded.activity_types or _DEFAULT_ACTIVITY_TYPES
            args = FetchArgs(
                segment=decoded.segment,
                entity_id=decoded.entity_id,
                party=ResolvedParty(id=decoded.entity_id, search_type=decoded.segment, name=None),
                limit=decoded.limit,
                activity_types=activity_types,
                since=decoded.since,
                until=decoded.until,
                consumed=decoded.consumed,
                active_activity_types=tuple(decoded.consumed.keys()),
            )
            logger.info(
                "activity_history.args.next",
                extra={
                    "segment": args.segment,
                    "entity_id": args.entity_id,
                    "active_streams": list(args.active_activity_types),
                    "limit": args.limit,
                    "since": args.since.isoformat() if args.since is not None else None,
                    "until": args.until.isoformat() if args.until is not None else None,
                },
            )
            return args
        case ActivityHistoryFirstPageInput(
            party_type=party_type,
            party_id=party_id,
            search=search,
            activity_types=activity_types,
            since=since,
            until=until,
            limit=limit,
        ):
            result = await resolve_party(
                ctx,
                client,
                search_type=segment_for(party_type),
                party_id=party_id,
                search=search,
            )
            if not isinstance(result, Resolved):
                logger.info(
                    "activity_history.args.unresolved",
                    extra={
                        "party_type": party_type,
                        "has_party_id": party_id is not None,
                        "has_search": search is not None,
                        "status": result.status,
                    },
                )
                return tool_result(unresolved_party_response(result))
            party = result.value
            effective_types = effective_activity_types(activity_types)
            args = FetchArgs(
                segment=segment_for(party_type),
                entity_id=party.id,
                party=party,
                limit=limit if limit is not None else get_activity_history_settings().page_size,
                activity_types=effective_types,
                since=since,
                until=until,
                consumed={},
                active_activity_types=effective_types,
            )
            logger.info(
                "activity_history.args.first",
                extra={
                    "segment": args.segment,
                    "entity_id": args.entity_id,
                    "activity_types": list(args.activity_types),
                    "limit": args.limit,
                    "since": args.since.isoformat() if args.since is not None else None,
                    "until": args.until.isoformat() if args.until is not None else None,
                },
            )
            return args
