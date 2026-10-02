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
from with_intelligence_mcp.with_intelligence_client import (
    NotEntitled,
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
        resolved_id = fund_id
        if resolved_id is None:
            if name is None:
                return FundNotFoundResponse(searched_for="", hint="Pass either name or fund_id.")
            try:
                matches, total = await self._search_by_name(name)
            except NotEntitled as error:
                return FundNotEntitledResponse(
                    searched_for=name,
                    hint=(
                        "With Intelligence refused the fund search for this account "
                        f"({error.path}) — the data is outside its licensed packages."
                    ),
                )
            if not matches:
                return FundNotFoundResponse(
                    searched_for=name,
                    hint=(
                        "No fund name contains that text. Matching is partial, so a shorter or "
                        "differently spelled fragment may find it."
                    ),
                )
            if len(matches) > 1:
                return FundAmbiguousResponse(
                    searched_for=name,
                    candidates=[
                        FundCandidateResponse(
                            id=match.id, name=match.name, updated_at=match.updated_at
                        )
                        for match in matches
                    ],
                    total_matches=total,
                )
            resolved_id = matches[0].id

        try:
            record = await self._fetch(resolved_id)
        except NotEntitled as error:
            return FundNotEntitledResponse(
                searched_for=name or str(resolved_id),
                hint=(
                    f"With Intelligence refused {error.path} for this account — "
                    "the data is outside its licensed packages."
                ),
            )
        if record is None:
            return FundNotFoundResponse(
                searched_for=name or str(resolved_id),
                hint=f"No fund with id {resolved_id}.",
            )
        return record

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
