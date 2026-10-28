"""Newest activity per party, for "who has gone quiet" questions.

One party-scoped `POST /entity-activities` per party, `pageSize` 1, sorted newest first — the
first row is the last activity in the window and `totalCount` is the count in it. A firm-wide
sweep cannot answer this: it saturates at 10000 rows, so a party missing from it is unknown, not
inactive. This runs through `SearchActivitiesQuery`, so a filter Backstop ignored is caught the
same way (`server_filter_ignored`). The per-user request gate on `BackstopClient` bounds how many
are in flight. The caller owns the party cap.

One party failing costs that party's answer, not the batch. `BATCH_ABORTING_ERRORS` (auth,
transient auth, rate limit) still abort: the rest would fail the same way. A non-`Exception`
(cancellation) is re-raised.
"""

import asyncio
import logging
from collections.abc import Sequence
from datetime import date

from mcp_observability import traced

from backstop_mcp.backstop_client import BATCH_ABORTING_ERRORS
from backstop_mcp.features.activity_history.entity_activity_type import EntityActivityType
from backstop_mcp.features.activity_history.internal_dto import (
    EntityActivitiesFetchDto,
    PartyLastActivityDto,
)
from backstop_mcp.features.activity_history.queries.search_activities_query import (
    SearchActivitiesQuery,
)
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.utils import sample_ids

logger = logging.getLogger(__name__)


def _outcome_counts(outcomes: Sequence[PartyLastActivityDto]) -> dict[str, int]:
    return {
        "failed": sum(1 for outcome in outcomes if outcome.error is not None),
        "without_activity": sum(
            1 for outcome in outcomes if outcome.fetch is not None and not outcome.fetch.rows
        ),
    }


class GetLastActivityForPartiesQuery:
    """Each party's newest activity in a window, and how many it had there."""

    def __init__(self, *, search_activities_query: SearchActivitiesQuery) -> None:
        self._search_activities_query: SearchActivitiesQuery = search_activities_query

    @traced(
        arguments=lambda args: {
            "requested": len(args["parties"]),
            "start_date": args["start_date"],
            "end_date": args["end_date"],
            "type_count": len(args["types"]),
        },
        result=_outcome_counts,
    )
    async def run(
        self,
        *,
        parties: Sequence[tuple[str, SearchType]],
        start_date: date,
        end_date: date,
        types: Sequence[EntityActivityType],
    ) -> tuple[PartyLastActivityDto, ...]:
        settled = await asyncio.gather(
            *(
                self._search_activities_query.run(
                    start_date=start_date,
                    end_date=end_date,
                    types=types,
                    party_id=party_id,
                    resource_type=search_type,
                    min_result_size=1,
                )
                for party_id, search_type in parties
            ),
            return_exceptions=True,
        )
        outcomes = tuple(
            self._outcome(party_id, search_type, result)
            for (party_id, search_type), result in zip(parties, settled, strict=True)
        )
        failed_ids = [outcome.party_id for outcome in outcomes if outcome.error is not None]
        if failed_ids:
            logger.warning(
                "Last activity lookups failed",
                extra={"count": len(failed_ids), "sample_ids": sample_ids(failed_ids)},
            )
        return outcomes

    def _outcome(
        self,
        party_id: str,
        search_type: SearchType,
        settled: EntityActivitiesFetchDto | BaseException,
    ) -> PartyLastActivityDto:
        if isinstance(settled, BaseException):
            if not isinstance(settled, Exception) or isinstance(settled, BATCH_ABORTING_ERRORS):
                raise settled
            logger.debug(
                "Last activity lookup failed",
                extra={"party_id": party_id, "search_type": search_type},
                exc_info=settled,
            )
            return PartyLastActivityDto(
                party_id=party_id,
                search_type=search_type,
                error=f"{type(settled).__name__}: {settled}",
            )
        return PartyLastActivityDto(party_id=party_id, search_type=search_type, fetch=settled)
