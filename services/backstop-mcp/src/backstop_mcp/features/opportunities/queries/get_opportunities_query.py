import asyncio
import logging
from datetime import date
from typing import Literal
from urllib.parse import quote

from pydantic import ValidationError

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.custom_fields import CustomFieldFilters, CustomFieldsService
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.opportunities.api_responses import OpportunityResource
from backstop_mcp.features.opportunities.resource_utils import MapOpportunityToResponseUtil
from backstop_mcp.features.opportunities.responses import (
    OpportunityResponse,
    PartyOpportunitiesResponse,
)

logger = logging.getLogger(__name__)

type OpportunityStatus = Literal["open", "closed", "all"]


class GetOpportunitiesQuery:
    """Walk one party's `/{segment}/{id}/opportunities` sub-collection."""

    def __init__(
        self,
        *,
        client: BackstopClient,
        map_opportunity_to_response_util: MapOpportunityToResponseUtil,
        custom_fields_service: CustomFieldsService,
    ) -> None:
        self._client: BackstopClient = client
        self.map_opportunity_to_response_util: MapOpportunityToResponseUtil = (
            map_opportunity_to_response_util
        )
        self._custom_fields_service: CustomFieldsService = custom_fields_service

    async def run(
        self,
        *,
        segment: SearchType,
        entity_id: str,
        status: OpportunityStatus = "all",
        custom_fields_filters: CustomFieldFilters,
    ) -> PartyOpportunitiesResponse:
        """Fetch, project, filter by `status`, and order newest stage-move first.

        The catalog load runs in parallel with the walk: `join_values` on each row would
        otherwise wait for a cold catalog after the last page, and a miss must be reported
        as `custom_fields_unavailable` rather than inferred from empty values.
        """
        pages, catalog = await asyncio.gather(
            self._client.paginate(
                f"/{segment}/{quote(entity_id, safe='')}/opportunities",
                schema=OpportunityResource,
                params={"include": "stage,stageHistory"},
                # Explicitly unbounded: `paginate` caps at 10_000 records by default, so passing
                # nothing would reintroduce a cap that never announces itself.
                max_records=None,
                page_size=100,
            ),
            self._custom_fields_service.load_catalog(),
        )
        opportunities_mapped: list[OpportunityResponse] = []
        for opportunity in pages.items:
            try:
                opportunity_mapped = await self.map_opportunity_to_response_util.run(
                    row=opportunity,
                    api_include_resources=pages.included,
                    custom_fields_filters=custom_fields_filters,
                )
                opportunities_mapped.append(opportunity_mapped)
            except ValidationError as exc:
                logger.warning(
                    "opportunities.record.unreadable",
                    extra={"opportunity_id": opportunity.id},
                    exc_info=exc,
                )

        selected = tuple(
            opportunity
            for opportunity in opportunities_mapped
            if _matches_status(opportunity, status)
        )
        opportunities = tuple(sorted(selected, key=_date_entered_order_key, reverse=True))
        result = PartyOpportunitiesResponse(
            opportunities=opportunities,
            total=len(opportunities_mapped),
            open_count=sum(
                1 for opportunity in opportunities_mapped if opportunity.is_open is True
            ),
            closed_count=sum(
                1 for opportunity in opportunities_mapped if opportunity.is_open is False
            ),
            custom_fields_unavailable=catalog is None,
        )
        logger.info(
            "opportunities.fetched",
            extra={
                "segment": segment,
                "entity_id": entity_id,
                "status": status,
                "total": result.total,
                "returned": len(result.opportunities),
            },
        )
        return result


def _matches_status(opportunity: OpportunityResponse, status: OpportunityStatus) -> bool:
    """Whether one deal belongs in an answer asked for `status`.

    A deal whose `isOpen` did not arrive matches neither `open` nor `closed` — it is as wrong to
    file it under one as the other — and is only returned by `all`.
    """
    if status == "all":
        return True
    if opportunity.is_open is None:
        return False
    return opportunity.is_open is (status == "open")


def _date_entered_order_key(opportunity: OpportunityResponse) -> tuple[bool, date]:
    """Sort key placing the most recent stage move first under `reverse=True`.

    The leading flag keeps a deal with no `date_entered_current_stage` last rather than letting
    it lead the list as an artificially old date would.
    """
    entered = opportunity.date_entered_current_stage
    return (entered is not None, entered or date.min)
