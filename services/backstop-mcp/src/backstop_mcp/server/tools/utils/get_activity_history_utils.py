"""Request shapes and first/next → fetch-input helpers for `get_activity_history`."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Annotated, ClassVar, Literal, Self

from fastmcp import Context
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.activity_history import (
    ActivityContinuationResponse,
    ActivityType,
    Segment,
)
from backstop_mcp.features.data_hygiene import ProvenanceAttributes
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.party_resolver import (
    PartyAmbiguousResponse,
    ResolvedPartyDto,
    resolve_party,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import NotFoundResponse, Resolved
from backstop_mcp.server.runtime import get_activity_history_settings

logger = logging.getLogger(__name__)

_DEFAULT_ACTIVITY_TYPES: tuple[ActivityType, ...] = (
    "meeting",
    "call",
    "note",
    "email",
    "document",
)
_NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ActivityHistoryFirstPageInput(BaseModel):
    """Start a new activity timeline for a party."""

    type: Literal["first"]
    search_type: Annotated[
        SearchType,
        Field(
            description=(
                "Which Backstop collection to resolve the party against — fold the caller's "
                "wording to one of the four. A company, firm, fund, institution, or manager is "
                "`organizations`; any human is `people`. Pick `contacts` or `employees` only "
                "when a prior resolve echoed one (echo it back — a contact or employee id is "
                "not a people id) or the caller clearly means an internal staff member."
            ),
        ),
    ]
    party_id: Annotated[
        _NonEmptyStr | None,
        Field(
            description=(
                "Trusted Backstop Party ID from a prior resolve echo (`id` / `search_type` / "
                "`name`). Never invent or guess. Exactly one of `party_id` or `search` must be "
                "provided."
            ),
        ),
    ] = None
    search: Annotated[
        _NonEmptyStr | None,
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
            min_length=1,
            description=(
                "Which streams to fetch: any of meeting, call, note, email, document. Defaults "
                "to all five (meeting, call, note, email, document). Must be non-empty when "
                "provided."
            ),
        ),
    ] = None
    since: Annotated[
        date | None,
        Field(
            description=(
                "Only include activity on or after this date. Must not be after `until` when "
                "both are set. There is no default window: omitting both `since` and `until` "
                "returns the newest activity regardless of age, which may be old."
            ),
        ),
    ] = None
    until: Annotated[
        date | None,
        Field(
            description=(
                "Only include activity on or before this date. Must not be before `since` when "
                "both are set. Future-dated meetings and calls are included, not filtered, "
                "when this is left unset."
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

    @field_validator("party_id", "search", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _exactly_one_selector(self) -> Self:
        if (self.party_id is None) == (self.search is None):
            raise ValueError("Exactly one of party_id or search must be provided")
        if self.party_id is not None and "/" in self.party_id:
            raise ValueError(f"party_id {self.party_id!r} must not contain '/'")
        return self

    @model_validator(mode="after")
    def _since_not_after_until(self) -> Self:
        if self.since is not None and self.until is not None and self.since > self.until:
            raise ValueError("since must not be after until")
        return self


class ActivityHistoryNextPageInput(BaseModel):
    """Fetch the next page of a timeline already in progress."""

    type: Literal["next"]
    search_type: Annotated[
        SearchType,
        Field(
            description=(
                "Trusted `search_type` copied from a prior `get_activity_history` response's "
                "`resolved.search_type`. Never invent or guess."
            ),
        ),
    ]
    entity_id: Annotated[
        _NonEmptyStr,
        Field(
            description=(
                "Trusted Backstop entity id copied from a prior `get_activity_history` "
                "response's `resolved.id`. Never invent or guess."
            ),
        ),
    ]
    next: Annotated[
        dict[ActivityType, ActivityContinuationResponse],
        Field(
            min_length=1,
            description=(
                "Map of `activity_type` to that stream's `next` from a prior response's "
                "`groups`. Omit streams whose `groups[type].next` is absent (or null) — those "
                "streams are exhausted. At least one entry is required. A one-entry map "
                "deepens a single stream; several entries continue those streams together. "
                "Never invent or guess."
            ),
        ),
    ]

    @model_validator(mode="after")
    def _entity_id_is_a_path_segment(self) -> Self:
        if "/" in self.entity_id:
            raise ValueError(f"entity_id {self.entity_id!r} must not contain '/'")
        return self


type ActivityHistoryPageInput = Annotated[
    ActivityHistoryFirstPageInput | ActivityHistoryNextPageInput,
    Field(discriminator="type"),
]


class PartyRecordResponse(ProvenanceAttributes):
    """Minimal attributes this tool needs from the party fetch: a display name plus provenance.

    `extra="ignore"`, not `"allow"` — unlike `get_person`/`get_organization`, this tool never
    surfaces the raw attribute dump, only `name` (for the resolve echo) and provenance (for
    `as_of`). People records often omit `name` and send `firstName`/`lastName` instead; keep
    those so a `type="next"` page (where `ResolvedParty.name` is None) can still rebuild it.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", populate_by_name=True)

    name: str | None = None
    first_name: str | None = Field(
        default=None, validation_alias=AliasChoices("firstName", "first_name")
    )
    last_name: str | None = Field(
        default=None, validation_alias=AliasChoices("lastName", "last_name")
    )


@dataclass(frozen=True, slots=True)
class FetchArgs:
    """Mode-agnostic inputs for the concurrent party + activity-type fan-out."""

    segment: Segment
    entity_id: str
    party: ResolvedPartyDto
    continuations: Mapping[ActivityType, ActivityContinuationResponse]


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
) -> FetchArgs | PartyAmbiguousResponse | NotFoundResponse:
    """Turn a first/next page input into shared fetch inputs, or an unresolved party response.

    Pydantic already validates/discriminates the wire shape (`ActivityHistoryPageInput`). This
    step is separate because it does async I/O: party resolve on `first`. `next` copies
    `search_type` / `entity_id` / continuations from the request with no HTTP.
    """
    match request:
        case ActivityHistoryNextPageInput(
            search_type=search_type, entity_id=entity_id, next=continuations
        ):
            args = FetchArgs(
                segment=search_type,
                entity_id=entity_id,
                party=ResolvedPartyDto(id=entity_id, search_type=search_type, name=None),
                continuations=dict(continuations),
            )
            logger.info(
                "activity_history.args.next",
                extra={
                    "segment": args.segment,
                    "entity_id": args.entity_id,
                    "activity_types": list(args.continuations),
                },
            )
            return args
        case ActivityHistoryFirstPageInput(
            party_id=party_id,
            search=search,
            search_type=search_type,
            activity_types=activity_types,
            since=since,
            until=until,
            limit=limit,
        ):
            result = await resolve_party(
                ctx,
                client,
                search_type=search_type,
                party_id=party_id,
                search=search,
            )
            if not isinstance(result, Resolved):
                logger.info(
                    "activity_history.args.unresolved",
                    extra={
                        "search_type": search_type,
                        "has_party_id": party_id is not None,
                        "has_search": search is not None,
                        "status": result.status,
                    },
                )
                return unresolved_party_response(result)
            party = result.value
            effective_types = effective_activity_types(activity_types)
            page_size = limit if limit is not None else get_activity_history_settings().page_size
            # Person quick-search uses shared PERSON_* types, so a hit may be contacts/
            # employees — follow `party.search_type` like `get_person`, not the requested one.
            args = FetchArgs(
                segment=party.search_type,
                entity_id=party.id,
                party=party,
                continuations={
                    activity_type: ActivityContinuationResponse(
                        limit=page_size,
                        offset=0,
                        since=since,
                        until=until,
                    )
                    for activity_type in effective_types
                },
            )
            logger.info(
                "activity_history.args.first",
                extra={
                    "segment": args.segment,
                    "entity_id": args.entity_id,
                    "activity_types": list(args.continuations),
                },
            )
            return args
