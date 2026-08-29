from datetime import date
from typing import Literal

from pydantic import ValidationError

from backstop_mcp.app import logger
from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.custom_fields import (
    CustomFieldFilters,
)
from backstop_mcp.features.entity_types import SearchType
from backstop_mcp.features.opportunities.queries.opportuntity_resource import (
    OpportunityResource,
)
from backstop_mcp.features.opportunities.resource_utils.map_opportunity_to_response_util import (
    MapOpportunityToResponseUtil,
)
from backstop_mcp.features.opportunities.responses import (
    GetOpportunitiesResponse,
    OpportunityResponse,
)

type OpportunityStatus = Literal["open", "closed", "all"]


class GetOpportunitiesQuery:
    def __init__(
        self,
        *,
        client: BackstopClient,
        map_opportunity_to_response_util: MapOpportunityToResponseUtil,
    ) -> None:
        self._client: BackstopClient = client
        self.map_opportunity_to_response_util: MapOpportunityToResponseUtil = (
            map_opportunity_to_response_util
        )

    async def run(
        self,
        *,
        segment: SearchType,
        entity_id: str,
        status: OpportunityStatus = "all",
        custom_fields_filters: CustomFieldFilters,
    ) -> GetOpportunitiesResponse | None:
        pages = await self._client.paginate(
            f"/{segment}/{entity_id}/opportunities",
            schema=OpportunityResource,
            params={"include": "stage,stageHistory"},
            # Explicitly unbounded: `paginate` caps at 10_000 records by default, so passing
            # nothing would reintroduce a cap that never announces itself.
            max_records=None,
            page_size=100,
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

        opportunities = tuple(sorted(opportunities_mapped, key=_date_entered_order_key))
        open_count = sum(1 for opportunity in pages.items if opportunity.attributes.is_open is True)
        closed_count = sum(
            1 for opportunity in pages.items if opportunity.attributes.is_open is False
        )
        result = GetOpportunitiesResponse(
            opportunities=opportunities,
            total=len(pages.items),
            open_count=open_count,
            closed_count=closed_count,
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


def _date_entered_order_key(opportunity: OpportunityResponse) -> tuple[bool, date]:
    """Sort key placing the most recent stage move first under `reverse=True`.

    The leading flag keeps a deal with no `date_entered_current_stage` last rather than letting
    it lead the list as an artificially old date would.
    """
    entered = opportunity.date_entered_current_stage
    return (entered is not None, entered or date.min)
