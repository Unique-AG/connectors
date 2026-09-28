import asyncio
import logging

from with_intelligence_mcp.features.investors.api_responses import InvestorExtendedAttributes
from with_intelligence_mcp.features.mandates.fetch_mandate import fetch_mandate
from with_intelligence_mcp.features.mandates.fetch_mandates_for_investor import (
    fetch_mandates_for_investor,
)
from with_intelligence_mcp.features.mandates.resource_utils import MapMandateToResponseUtil
from with_intelligence_mcp.features.mandates.responses import (
    InvestorMandatesResponse,
    MandateResponse,
)
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient

logger = logging.getLogger(__name__)


class GetMandatesQuery:
    def __init__(
        self,
        *,
        client: WithIntelligenceClient,
        map_mandate_to_response_util: MapMandateToResponseUtil,
    ) -> None:
        self._client: WithIntelligenceClient = client
        self._map_mandate_to_response_util: MapMandateToResponseUtil = map_mandate_to_response_util

    async def run(
        self,
        *,
        investor: InvestorExtendedAttributes,
        page: int,
        limit: int,
        updated_since: str | None,
    ) -> InvestorMandatesResponse:
        listed, total = await fetch_mandates_for_investor(
            self._client,
            investor.id,
            page=page,
            limit=limit,
            updated_since=updated_since,
        )
        details = await asyncio.gather(*(fetch_mandate(self._client, entry.id) for entry in listed))
        mandates = [
            self._map_mandate_to_response_util.run(record=detail)
            if detail
            else MandateResponse(id=listed[index].id)
            for index, detail in enumerate(details)
        ]
        response = InvestorMandatesResponse(
            investor_id=investor.id,
            investor_name=investor.name,
            mandates=mandates,
            total=total,
            returned=len(mandates),
            page=page,
            has_more=(page - 1) * limit + len(mandates) < total,
        )
        logger.info(
            "mandates.investor.fetched",
            extra={"investor_id": investor.id, "returned": response.returned, "total": total},
        )
        return response
