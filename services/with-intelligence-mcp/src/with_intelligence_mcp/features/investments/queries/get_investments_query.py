import asyncio
import logging

from with_intelligence_mcp.features.investments.fetch_investment import fetch_investment
from with_intelligence_mcp.features.investments.fetch_investments_for_investor import (
    fetch_investments_for_investor,
)
from with_intelligence_mcp.features.investments.resource_utils import MapPositionToResponseUtil
from with_intelligence_mcp.features.investments.responses import (
    InvestorPositionsResponse,
    PositionResponse,
)
from with_intelligence_mcp.features.investors.api_responses import InvestorExtendedAttributes
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient

logger = logging.getLogger(__name__)


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
        listed, total = await fetch_investments_for_investor(
            self._client,
            investor.id,
            limit=limit,
            updated_since=updated_since,
        )
        details = await asyncio.gather(
            *(fetch_investment(self._client, position.id) for position in listed)
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
