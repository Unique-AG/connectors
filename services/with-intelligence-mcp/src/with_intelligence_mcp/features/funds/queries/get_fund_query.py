import logging

from pydantic import TypeAdapter

from with_intelligence_mcp.features.funds.api_responses import (
    FundExtendedAttributes,
    FundListItemAttributes,
)
from with_intelligence_mcp.features.funds.responses import (
    FundAmbiguousResponse,
    FundCandidateResponse,
    FundNotEntitledResponse,
    FundNotFoundResponse,
    FundProfileResponse,
)
from with_intelligence_mcp.utils.resolve import resolve_by_name_or_id
from with_intelligence_mcp.with_intelligence_client import (
    NotFound,
    Page,
    QueryValue,
    WithIntelligenceClient,
)

logger = logging.getLogger(__name__)
_FUND_RESPONSE = TypeAdapter(FundExtendedAttributes)
_FUNDS_PAGE = TypeAdapter(Page[FundListItemAttributes])

type GetFundResult = (
    FundProfileResponse | FundAmbiguousResponse | FundNotEntitledResponse | FundNotFoundResponse
)
type _FundResolution = (
    FundExtendedAttributes | FundAmbiguousResponse | FundNotEntitledResponse | FundNotFoundResponse
)


class GetFundQuery:
    def __init__(self, *, client: WithIntelligenceClient) -> None:
        self._client: WithIntelligenceClient = client

    async def run(self, *, name: str | None, fund_id: int | None) -> GetFundResult:
        record = await self._resolve(name=name, fund_id=fund_id)
        if not isinstance(record, FundExtendedAttributes):
            logger.info("fund.resolve.unresolved", extra={"status": record.status})
            return record
        response = FundProfileResponse.from_attributes(record)
        logger.info("fund.fetched", extra={"fund_id": response.id})
        return response

    async def _resolve(self, *, name: str | None, fund_id: int | None) -> _FundResolution:
        return await resolve_by_name_or_id(
            name=name,
            record_id=fund_id,
            kind="fund",
            search=self._search_by_name,
            fetch=self._fetch,
            not_found=FundNotFoundResponse,
            not_entitled=FundNotEntitledResponse,
            ambiguous=FundAmbiguousResponse,
            candidate=FundCandidateResponse,
        )

    async def _search_by_name(self, name: str) -> tuple[list[FundListItemAttributes], int]:
        params: dict[str, QueryValue] = {"name": [name]}
        if self._client.asset_class_groups:
            params["asset_class_group"] = list(self._client.asset_class_groups)
        page = await self._client.get_page("/v3/funds", _FUNDS_PAGE, params, page=1, page_size=10)
        return page.results, page.pagination.total

    async def _fetch(self, fund_id: int) -> FundExtendedAttributes | None:
        try:
            return await self._client.get_json(f"/v3/funds/{fund_id}", _FUND_RESPONSE)
        except NotFound:
            return None
