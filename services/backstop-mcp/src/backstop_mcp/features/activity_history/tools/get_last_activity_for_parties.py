"""`get_last_activity_for_parties`: the newest activity per party, for inactivity questions.

A firm-wide `search_activities` sweep saturates at 10000 rows, so a party missing from it is
unknown, not inactive. This asks Backstop once per party instead.
"""

import logging
from datetime import date
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from opentelemetry import trace
from pydantic import BaseModel, Field

from backstop_mcp.features.activity_history import (
    ENTITY_ACTIVITY_TYPES,
    EntityActivityType,
    GetLastActivityForPartiesQuery,
    GetLastActivityForPartiesResponse,
    LastActivityForPartiesResolvedResponse,
    PartyLastActivityResponse,
    SearchActivitiesUnavailableResponse,
)
from backstop_mcp.features.activity_history.dependencies import (
    get_last_activity_for_parties_query_factory,
)
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.models import CoercedId, published_output_schema
from backstop_mcp.utils import date_window

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

_MAX_PARTIES = 100
_SUBSTANTIVE_TYPES: tuple[EntityActivityType, ...] = tuple(
    activity_type for activity_type in ENTITY_ACTIVITY_TYPES if activity_type != "email_blast"
)
_FALLBACK_MESSAGE = (
    "POST /entity-activities did not answer for any party, so no party could be checked. "
    "This is not 'no activity'. Call get_activity_history per party instead."
)


class PartyRef(BaseModel):
    """One party to check, as a prior tool echoed it."""

    # Backstop party ids are numeric. Anything else would fail `entityId` inside the batch and
    # read as the endpoint being down, so it is rejected here.
    party_id: CoercedId = Field(
        pattern=r"^[0-9]+$",
        description=(
            "Trusted party id from a prior response — for a deal, the row's `investor.id`. "
            "Never invent one."
        ),
    )
    search_type: SearchType = Field(
        description=(
            "Collection `party_id` belongs to — for a deal, the row's `investor.search_type`. "
            "Never assume organizations."
        )
    )


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(GetLastActivityForPartiesResponse),
)
async def get_last_activity_for_parties(
    parties: Annotated[
        list[PartyRef],
        Field(
            min_length=1,
            max_length=_MAX_PARTIES,
            description=(
                f"One to {_MAX_PARTIES} parties. Duplicates are checked once. For more, call "
                "again with the next batch."
            ),
        ),
    ],
    start_date: Annotated[
        date | None,
        Field(
            description=(
                "Inclusive start of the window. Omit for one year before `end_date`. Keep it "
                "wider than the longest inactivity bucket you report, so an older last "
                "activity still shows up with its date."
            ),
        ),
    ] = None,
    end_date: Annotated[
        date | None,
        Field(description="Inclusive end of the window. Omit for today."),
    ] = None,
    types: Annotated[
        list[EntityActivityType] | None,
        Field(
            description=(
                "Activity types that count, OR. Default is every type except email_blast "
                "(meeting, meeting_call, note, email, document) — mass mailings are not "
                "contact. Narrow to ['meeting', 'meeting_call'] when the user means meetings "
                "and calls only, and say which you used."
            ),
        ),
    ] = None,
    get_last_activity_for_parties_query: GetLastActivityForPartiesQuery = Depends(
        get_last_activity_for_parties_query_factory
    ),
) -> GetLastActivityForPartiesResponse:
    """Newest activity and in-window count for each party — who has gone quiet, and since when.

    Use for "which deals / investors have had no activity in 30, 60, 90 days": take the
    open deals from search_opportunities with the `investor` field, pass each distinct
    `investor.id` with `investor.search_type` here, then bucket by
    `days_since_last_activity` (`none_in_window` is older than the whole window). One
    request per party, so the answer covers
    every party — never infer inactivity from a party's absence in a firm-wide
    search_activities sample, which caps and saturates.

    A party with `status` `unknown` could not be checked (the search failed or Backstop
    ignored a filter). Report it as unchecked, never as inactive. `activity_count` is
    what this credential can see.

    Call like: {"parties": [{"party_id": "<investor.id>", "search_type": "organizations"}],
    "start_date": "2025-09-30", "types": ["meeting", "meeting_call", "note", "email"]}
    """
    start, end = date_window(start_date, end_date, today=date.today())
    selected_types = tuple(types) if types else _SUBSTANTIVE_TYPES
    keys: list[tuple[str, SearchType]] = [(party.party_id, party.search_type) for party in parties]
    distinct = tuple(dict.fromkeys(keys))
    with _tracer.start_as_current_span("activity_history.last_activity") as span:
        span.set_attribute("parties", len(distinct))
        logger.info(
            "activity_history.last_activity.start",
            extra={"parties": len(distinct), "types": list(selected_types)},
        )
        outcomes = await get_last_activity_for_parties_query.run(
            parties=distinct, start_date=start, end_date=end, types=selected_types
        )
    if all(outcome.error is not None for outcome in outcomes):
        return SearchActivitiesUnavailableResponse(message=_FALLBACK_MESSAGE)
    rows = tuple(PartyLastActivityResponse.from_dto(outcome, end_date=end) for outcome in outcomes)
    return LastActivityForPartiesResolvedResponse(
        start_date=start,
        end_date=end,
        types=selected_types,
        parties=rows,
        unknown_count=sum(1 for row in rows if row.status == "unknown"),
    )
