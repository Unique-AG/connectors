"""Newest activity per party, for "who has gone quiet" questions.

One party-scoped `POST /entity-activities` per party, `pageSize` 1, sorted newest first — the
first row is the last activity in the window and `totalCount` is the count in it. A firm-wide
sweep cannot answer this: it saturates at 10000 rows, so a party missing from it is unknown, not
inactive. This runs through `SearchActivitiesQuery`, so a filter Backstop ignored is caught the
same way (`server_filter_ignored`). The per-user request gate on `BackstopClient` bounds how many
are in flight. The caller owns the party cap.

One party failing costs that party's answer, not the batch. Auth and rate-limit errors still
abort: the rest would fail the same way. A non-`Exception` (cancellation) is re-raised.
"""

import asyncio
import logging
from collections.abc import Sequence
from datetime import date

from opentelemetry import trace

from backstop_mcp.backstop_client import (
    BackstopAuthError,
    BackstopRateLimitError,
)
from backstop_mcp.features.activity_history.entity_activity_type import EntityActivityType
from backstop_mcp.features.activity_history.internal_dto import (
    EntityActivitiesFetchDto,
    PartyLastActivityDto,
)
from backstop_mcp.features.activity_history.queries.search_activities_query import (
    SearchActivitiesQuery,
)
from backstop_mcp.features.entity_types import SearchType

logger = logging.getLogger(__name__)
_tracer = trace.get_tracer(__name__)

_ABORTS_BATCH = (BackstopAuthError, BackstopRateLimitError)


class GetLastActivityForPartiesQuery:
    """Each party's newest activity in a window, and how many it had there."""

    def __init__(self, *, search_activities_query: SearchActivitiesQuery) -> None:
        self._search_activities_query: SearchActivitiesQuery = search_activities_query

    async def run(
        self,
        *,
        parties: Sequence[tuple[str, SearchType]],
        start_date: date,
        end_date: date,
        types: Sequence[EntityActivityType],
    ) -> tuple[PartyLastActivityDto, ...]:
        with _tracer.start_as_current_span("activity_history.query.last_activity") as span:
            span.set_attribute("requested", len(parties))
            settled = await asyncio.gather(
                *(
                    self._search_activities_query.run(
                        start_date=start_date,
                        end_date=end_date,
                        types=types,
                        party_id=party_id,
                        resource_type=search_type,
                        max_rows=1,
                        page_size=1,
                    )
                    for party_id, search_type in parties
                ),
                return_exceptions=True,
            )
            outcomes = tuple(
                self._outcome(party_id, search_type, result)
                for (party_id, search_type), result in zip(parties, settled, strict=True)
            )
            logger.info(
                "activity_history.last_activity.fetched",
                extra={
                    "requested": len(parties),
                    "failed": sum(1 for outcome in outcomes if outcome.error is not None),
                    "without_activity": sum(
                        1
                        for outcome in outcomes
                        if outcome.fetch is not None and not outcome.fetch.rows
                    ),
                },
            )
            return outcomes

    def _outcome(
        self,
        party_id: str,
        search_type: SearchType,
        settled: EntityActivitiesFetchDto | BaseException,
    ) -> PartyLastActivityDto:
        if isinstance(settled, BaseException):
            if not isinstance(settled, Exception) or isinstance(settled, _ABORTS_BATCH):
                raise settled
            logger.warning(
                "activity_history.last_activity.party_failed",
                extra={"party_id": party_id, "search_type": search_type},
                exc_info=settled,
            )
            return PartyLastActivityDto(
                party_id=party_id,
                search_type=search_type,
                error=f"{type(settled).__name__}: {settled}",
            )
        return PartyLastActivityDto(party_id=party_id, search_type=search_type, fetch=settled)
