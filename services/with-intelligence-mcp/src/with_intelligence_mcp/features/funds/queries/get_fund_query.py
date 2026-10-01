import logging

from with_intelligence_mcp.features.funds.api_responses import FundExtendedAttributes
from with_intelligence_mcp.features.funds.resolve_fund import resolve_fund
from with_intelligence_mcp.features.funds.responses import (
    FundAmbiguousResponse,
    FundNotEntitledResponse,
    FundNotFoundResponse,
    FundProfileResponse,
)
from with_intelligence_mcp.with_intelligence_client import WithIntelligenceClient

logger = logging.getLogger(__name__)

type GetFundResult = (
    FundProfileResponse | FundAmbiguousResponse | FundNotEntitledResponse | FundNotFoundResponse
)


class GetFundQuery:
    def __init__(self, *, client: WithIntelligenceClient) -> None:
        self._client: WithIntelligenceClient = client

    async def run(self, *, name: str | None, fund_id: int | None) -> GetFundResult:
        record = await resolve_fund(self._client, name, fund_id)
        if not isinstance(record, FundExtendedAttributes):
            logger.info("fund.resolve.unresolved", extra={"status": record.status})
            return record
        response = FundProfileResponse.from_attributes(record)
        logger.info("fund.fetched", extra={"fund_id": response.id})
        return response
