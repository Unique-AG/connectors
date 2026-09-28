import logging

from with_intelligence_mcp.features.investors.api_responses import InvestorExtendedAttributes
from with_intelligence_mcp.features.investors.queries.resolve_investor_record_query import (
    ResolveInvestorRecordQuery,
)
from with_intelligence_mcp.features.investors.resource_utils import MapInvestorToResponseUtil
from with_intelligence_mcp.features.investors.responses import (
    InvestorAmbiguousResponse,
    InvestorNotEntitledResponse,
    InvestorNotFoundResponse,
    InvestorProfileResponse,
)

logger = logging.getLogger(__name__)


class GetInvestorQuery:
    def __init__(
        self,
        *,
        resolve_investor_record_query: ResolveInvestorRecordQuery,
        map_investor_to_response_util: MapInvestorToResponseUtil,
    ) -> None:
        self._resolve_investor_record_query: ResolveInvestorRecordQuery = (
            resolve_investor_record_query
        )
        self._map_investor_to_response_util: MapInvestorToResponseUtil = (
            map_investor_to_response_util
        )

    async def run(
        self, *, name: str | None, investor_id: int | None
    ) -> (
        InvestorProfileResponse
        | InvestorAmbiguousResponse
        | InvestorNotEntitledResponse
        | InvestorNotFoundResponse
    ):
        record = await self._resolve_investor_record_query.run(name=name, investor_id=investor_id)
        if not isinstance(record, InvestorExtendedAttributes):
            logger.info(
                "investor.resolve.unresolved",
                extra={"status": record.status},
            )
            return record
        response = self._map_investor_to_response_util.run(record=record)
        logger.info("investor.fetched", extra={"investor_id": response.id})
        return response
