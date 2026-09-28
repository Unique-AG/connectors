import asyncio
import logging

from pydantic import TypeAdapter

from with_intelligence_mcp.features.investments.api_responses import (
    InvestmentExtendedAttributes,
    InvestmentListItemAttributes,
)
from with_intelligence_mcp.features.investments.resource_utils import MapPositionToResponseUtil
from with_intelligence_mcp.features.investments.responses import (
    InvestorPositionsResponse,
    PositionResponse,
)
from with_intelligence_mcp.features.investors.api_responses import InvestorExtendedAttributes
from with_intelligence_mcp.with_intelligence_client import (
    NotEntitled,
    NotFound,
    Page,
    QueryValue,
    WithIntelligenceClient,
)

logger = logging.getLogger(__name__)
_INVESTMENTS_PATH = "/v3/investments"
_INVESTMENT_RESPONSE = TypeAdapter(InvestmentExtendedAttributes)
_INVESTMENTS_PAGE = TypeAdapter(Page[InvestmentListItemAttributes])


class GetInvestmentsQuery:
    def __init__(
        self,
        *,
        client: WithIntelligenceClient,
        map_position_to_response_util: MapPositionToResponseUtil,
    ) -> None:
        self._client: WithIntelligenceClient = client
        self._map_position_to_response_util: MapPositionToResponseUtil = (
            map_position_to_response_util
        )

    async def run(
        self,
        *,
        investor: InvestorExtendedAttributes,
        limit: int,
        updated_since: str | None,
    ) -> InvestorPositionsResponse:
        listed, total = await _fetch_investments_for_investor(
            self._client,
            investor.id,
            limit=limit,
            updated_since=updated_since,
        )
        details = await asyncio.gather(
            *(_fetch_investment(self._client, position.id) for position in listed)
        )
        positions = [
            self._map_position_to_response_util.run(record=detail)
            if detail
            else PositionResponse(id=listed[index].id)
            for index, detail in enumerate(details)
        ]
        response = InvestorPositionsResponse(
            investor_id=investor.id,
            investor_name=investor.name,
            positions=positions,
            total=total,
            returned=len(positions),
        )
        logger.info(
            "investments.investor.fetched",
            extra={"investor_id": investor.id, "returned": response.returned, "total": total},
        )
        return response


async def _fetch_investments_for_investor(
    client: WithIntelligenceClient,
    investor_id: int,
    *,
    limit: int,
    updated_since: str | None,
) -> tuple[list[InvestmentListItemAttributes], int]:
    params: dict[str, QueryValue] = {
        "investor_id": [investor_id],
        "sort[updated_at]": "desc",
    }
    if client.asset_class_groups:
        params["asset_class_group"] = list(client.asset_class_groups)
    if updated_since is not None:
        params["updated_at[from]"] = updated_since

    page = await client.get_page(
        _INVESTMENTS_PATH, _INVESTMENTS_PAGE, params, page=1, page_size=limit
    )
    return page.results, page.pagination.total


async def _fetch_investment(
    client: WithIntelligenceClient, investment_id: int
) -> InvestmentExtendedAttributes | None:
    try:
        return await client.get_json(f"{_INVESTMENTS_PATH}/{investment_id}", _INVESTMENT_RESPONSE)
    except NotEntitled, NotFound:
        return None
